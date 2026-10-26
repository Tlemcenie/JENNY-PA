"""pipeline d'ingestion rag."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from jenny.core.logging import get_logger
from jenny.rag.embeddings import estimate_tokens

if TYPE_CHECKING:
    from collections.abc import Callable

    from jenny.rag.embeddings import BaseEmbedder
    from jenny.rag.vector_store import PgVectorStore

logger = get_logger(__name__)

# part de la fenêtre utilisée
WINDOW_SHARE = 0.8
# fenêtre par défaut (mpnet)
DEFAULT_WINDOW = 128
# le prompt coupe à 300
MAX_CHUNK_CHARS = 300
# overlap ~15 % du budget
OVERLAP_SHARE = 0.15
# phrase entière si assez courte
WHOLE_UNIT_FACTOR = 2.3
# titre max dans l'embedding
MAX_HEADER_CHARS = 120

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
# après ";" ou avant "•"
_CLAUSE_RE = re.compile(r"(?<=;)\s*|\s+(?=[•·])")
_COMMA_RE = re.compile(r"(?<=,)\s+")

# libellés de catégorie
_CATEGORY_LABELS = {
    "horaires": "Horaires",
    "tarifs": "Tarifs",
    "prestations": "Prestations",
    "politique": "Politique du salon",
    "paiement": "Paiement",
    "acces": "Accès",
    "produits": "Produits",
    "equipe": "Équipe",
    "enfants": "Enfants",
    "mariage": "Mariage",
    "fidelite": "Fidélité",
    "rendez-vous": "Rendez-vous",
    "conseils": "Conseils",
    "confort": "Confort",
}


def embed_header(title: str = "", category: str = "") -> str:
    """En-tête titre + catégorie."""
    title = re.sub(r"\s+", " ", (title or "").strip())[:MAX_HEADER_CHARS]
    label = _CATEGORY_LABELS.get((category or "").lower(), "")
    if label and label.lower() in title.lower():
        label = ""
    return " — ".join(p for p in (title, label) if p)


def build_embed_text(content: str, title: str = "", category: str = "") -> str:
    """Texte réellement vectorisé."""
    header = embed_header(title, category)
    return f"{header}\n{content}" if header else content


@dataclass
class DocumentChunk:
    """chunk prêt à indexer."""

    id: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid4())


@dataclass
class _Unit:
    text: str
    tokens: int
    new_line: bool  # commence une ligne
    para: bool = False  # ligne vide avant

    @property
    def sep(self) -> str:
        """Lien avec le texte d'avant."""
        if self.para:
            return "\n\n"
        return "\n" if self.new_line else " "


class DocumentIngester:
    """ingère les documents en base."""

    def __init__(
        self,
        embedder: BaseEmbedder | None = None,
        vector_store: PgVectorStore | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        collection: str = "default",
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        # chunk_size/overlap en caractères
        self.chunk_size = chunk_size or MAX_CHUNK_CHARS
        self.chunk_overlap = chunk_overlap
        self.collection = collection
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    # ── budgets ──

    @property
    def token_budget(self) -> int:
        """Budget tokens d'un fragment."""
        if self._max_tokens:
            return self._max_tokens
        window = getattr(self.embedder, "max_tokens", None) or DEFAULT_WINDOW
        return max(16, int(window * WINDOW_SHARE))

    def _counter(self) -> Callable[[str], int]:
        count = getattr(self.embedder, "count_tokens", None)
        if count is None:
            return estimate_tokens

        def safe(text: str) -> int:
            try:
                return int(count(text))
            except Exception:
                return estimate_tokens(text)

        return safe

    # ── découpage ──

    def _split_long(self, text: str, max_tok: int, max_chars: int, count) -> list[str]:
        """Coupe un bloc trop long."""
        if count(text) <= max_tok and len(text) <= max_chars:
            return [text]
        for splitter in (_SENTENCE_RE, _CLAUSE_RE, _COMMA_RE):
            parts = [p.strip() for p in splitter.split(text) if p and p.strip()]
            if len(parts) > 1:
                out: list[str] = []
                for p in parts:
                    out.extend(self._split_long(p, max_tok, max_chars, count))
                return out
        # dernier recours : par mots
        words = text.split()
        out, cur = [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and (count(cand) > max_tok or len(cand) > max_chars):
                out.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            out.append(cur)
        return out

    def _sections(self, text: str) -> list[tuple[str, list[tuple[str, bool]]]]:
        """Sections (titre, lignes + paragraphe)."""
        sections: list[tuple[str, list[tuple[str, bool]]]] = [("", [])]
        gap = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                gap = True
                continue
            m = _HEADING_RE.match(line)
            if m:
                sections.append((m.group(1).strip(), []))
                gap = False
                continue
            lines = sections[-1][1]
            lines.append((line, gap and bool(lines)))
            gap = False
        kept = [(t, lines) for t, lines in sections if lines]
        if not kept:
            # que des titres : on garde
            kept = [("", [(ln.strip(), False) for ln in text.splitlines() if ln.strip()])]
        return [(t, lines) for t, lines in kept if lines]

    def _overlap(self, units: list[_Unit], max_tok: int, max_chars: int) -> str:
        """Fin du fragment à répéter."""
        if not units:
            return ""
        picked: list[str] = []
        tok = 0
        # phrases entières d'abord
        whole_tok, whole_chars = (
            int(max_tok * WHOLE_UNIT_FACTOR),
            int(max_chars * WHOLE_UNIT_FACTOR),
        )
        for u in reversed(units[1:]):
            if tok + u.tokens > whole_tok or sum(map(len, picked)) + len(u.text) > whole_chars:
                break
            picked.insert(0, u.text)
            tok += u.tokens
        if picked:
            return " ".join(picked)
        # sinon les derniers mots
        words = units[-1].text.split()
        tail: list[str] = []
        for w in reversed(words):
            if len(" ".join([w, *tail])) > max_chars:
                break
            tail.insert(0, w)
        return " ".join(tail) if len(tail) < len(words) else ""

    def chunk_text(
        self,
        text: str,
        metadata: dict | None = None,
        reserved_tokens: int = 0,
    ) -> list[DocumentChunk]:
        """découpe en fragments de sens."""
        count = self._counter()
        budget = max(16, self.token_budget - reserved_tokens)
        max_chars = self.chunk_size
        if self.chunk_overlap is not None:
            ov_chars = self.chunk_overlap
        else:
            ov_chars = int(max_chars * OVERLAP_SHARE)
        ov_tokens = self._overlap_tokens or int(budget * OVERLAP_SHARE)

        chunks: list[DocumentChunk] = []

        def emit(section: str, items: list[_Unit], overlap: str) -> None:
            body = body_of(items, overlap)
            content = f"{section}\n{body}" if section else body
            meta = {**(metadata or {}), "chunk_index": len(chunks)}
            if section:
                meta["section"] = section
            if overlap:
                meta["overlap_chars"] = len(overlap)
            # pour recoller à l'identique
            if items[0].sep != "\n":
                meta["sep"] = items[0].sep
            chunks.append(DocumentChunk(content=content, metadata=meta))

        def body_of(items: list[_Unit], prefix: str) -> str:
            out = prefix
            for u in items:
                out = f"{out}{u.sep}{u.text}" if out else u.text
            return out

        for section, lines in self._sections(text or ""):
            head_tok = count(section) + 1 if section else 0
            head_chars = len(section) + 1 if section else 0
            room_tok = max(8, budget - head_tok)
            room_chars = max(40, max_chars - head_chars)

            units: list[_Unit] = []
            for line, para in lines:
                for i, part in enumerate(self._split_long(line, room_tok, room_chars, count)):
                    units.append(_Unit(part, count(part), new_line=i == 0, para=para and i == 0))

            cur: list[_Unit] = []
            cur_tok = 0
            overlap_text = ""

            for u in units:
                cand_tok = cur_tok + u.tokens + 1
                cand_len = len(body_of([*cur, u], overlap_text))
                if cur and (cand_tok > room_tok or cand_len > room_chars):
                    emit(section, cur, overlap_text)
                    overlap_text = self._overlap(cur, ov_tokens, ov_chars)
                    cur, cur_tok = [], count(overlap_text) if overlap_text else 0
                    # l'overlap doit laisser la place
                    if overlap_text and (
                        cur_tok + u.tokens + 1 > room_tok
                        or len(overlap_text) + len(u.sep) + len(u.text) > room_chars
                    ):
                        overlap_text, cur_tok = "", 0
                cur.append(u)
                cur_tok += u.tokens + 1
            if cur:
                emit(section, cur, overlap_text)

        logger.info("ingestion.chunked", num_chunks=len(chunks), budget=budget)
        return chunks

    async def ingest_text(
        self,
        content: str,
        metadata: dict | None = None,
    ) -> int:
        """ingère un texte."""
        meta = metadata or {}
        chunks = self.chunk_text(content, meta)
        if not chunks:
            return 0

        # embeddings titre + texte
        if self.embedder is not None:
            texts = [
                build_embed_text(c.content, meta.get("title", ""), meta.get("category", ""))
                for c in chunks
            ]
            embed = getattr(self.embedder, "embed_passages", None) or self.embedder.embed_batch
            embeddings = await embed(texts)
            for chunk, embedding in zip(chunks, embeddings, strict=False):
                chunk.embedding = embedding
        else:
            logger.warning("ingestion.no_embedder")

        # stockage
        if self.vector_store is not None and chunks[0].embedding is not None:
            documents = [
                {
                    "content": c.content,
                    "embedding": c.embedding,
                    "metadata": c.metadata,
                }
                for c in chunks
                if c.embedding is not None
            ]
            await self.vector_store.add_documents(documents)
        else:
            logger.warning("ingestion.no_vector_store")

        logger.info("ingestion.done", num_chunks=len(chunks))
        return len(chunks)

    async def ingest_file(
        self,
        file_path: str | Path,
        metadata: dict | None = None,
    ) -> int:
        """ingère un fichier."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier non trouvé : {path}")

        content = path.read_text(encoding="utf-8")
        file_metadata = {
            "source": str(path),
            "filename": path.name,
            **(metadata or {}),
        }

        logger.info("ingestion.file", path=str(path), size=len(content))
        return await self.ingest_text(content, file_metadata)

    async def ingest_directory(
        self,
        directory: str | Path,
        extensions: list[str] | None = None,
        metadata: dict | None = None,
    ) -> int:
        """ingère tout un dossier."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Répertoire non trouvé : {dir_path}")

        exts = extensions or [".txt", ".md"]
        total_chunks = 0

        for file_path in sorted(dir_path.rglob("*")):
            if file_path.suffix in exts and file_path.is_file():
                chunks = await self.ingest_file(file_path, metadata)
                total_chunks += chunks

        logger.info(
            "ingestion.directory_done",
            directory=str(dir_path),
            total_chunks=total_chunks,
        )
        return total_chunks


def reassemble(chunks: list[tuple[str, dict]]) -> str:
    """Recolle les fragments d'une entrée."""
    out = ""
    last_section = ""
    for content, meta in sorted(chunks, key=lambda c: (c[1] or {}).get("chunk_index") or 0):
        meta = meta or {}
        body = content or ""
        section = meta.get("section") or ""
        if section and body.startswith(section + "\n"):
            body = body[len(section) + 1 :]
        ov = int(meta.get("overlap_chars") or 0)
        if ov:
            body = body[ov:].lstrip()
        sep = meta.get("sep") or "\n"
        if section and section != last_section:
            out = f"{out}\n## {section}" if out else f"## {section}"
            sep = "\n"
        last_section = section
        if body:
            out = f"{out}{sep}{body}" if out else body
    return out
