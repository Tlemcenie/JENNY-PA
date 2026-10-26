"""Service de base de connaissances métier (persisté en PostgreSQL).

Permet au propriétaire d'un business d'ajouter des informations
que Jenny mémorise et utilise pour répondre :
- Texte libre (horaires, tarifs, politique, FAQ)
- Fichiers PDF (carte de prestations, règlement intérieur)

Le contenu est découpé en chunks, vectorisé (embeddings) et stocké dans
la table `document_embeddings` (scopée par business). Jenny s'y réfère via
le retriever RAG pour répondre aux clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from jenny.core.logging import get_logger
from jenny.rag.embeddings import get_default_embedder
from jenny.rag.ingestion import DocumentIngester, build_embed_text, embed_header, reassemble
from jenny.rag.retriever import embed_query
from jenny.rag.vector_store import PgVectorStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.rag.embeddings import BaseEmbedder

logger = get_logger(__name__)

# clés posées par le découpage
LAYOUT_KEYS = frozenset(
    {
        "knowledge_id",
        "title",
        "category",
        "source",
        "section",
        "overlap_chars",
        "sep",
        "chunk_index",
    }
)
# coupe de l'aperçu (route)
PREVIEW_CHARS = 200
_ELLIPSIS = "..."
# un mot fini à la main
_PREVIEW_SLACK = 20
# aperçu retouché, pas réécrit
_PREVIEW_SIMILARITY = 0.8


def restore_preview_tail(new: str, old: str, preview_chars: int = PREVIEW_CHARS) -> str:
    """Recolle la fin cachée par l'aperçu."""
    if len(old) <= preview_chars:
        return new
    body = new.rstrip()
    if not body.endswith(_ELLIPSIS):
        return new
    body = body[: -len(_ELLIPSIS)]
    # doit ressembler à l'aperçu
    if len(body) > preview_chars + _PREVIEW_SLACK:
        return new
    seen = old[:preview_chars]
    if SequenceMatcher(None, seen, body, autojunk=False).ratio() < _PREVIEW_SIMILARITY:
        return new
    cut = preview_chars
    window = old[: preview_chars + _PREVIEW_SLACK]
    blocks = SequenceMatcher(None, window, body, autojunk=False).get_matching_blocks()
    last = blocks[-2] if len(blocks) > 1 else None
    # mot coupé complété à la main
    if last and last.b + last.size == len(body) and last.a < preview_chars < last.a + last.size:
        cut = last.a + last.size
    return body + old[cut:]


@dataclass
class KnowledgeEntry:
    """Entrée logique dans la base de connaissances (groupe de chunks)."""

    id: str = ""
    business_id: str = ""
    title: str = ""
    content: str = ""
    source: str = "text"  # "text", "pdf"
    category: str = "general"  # "horaires", "tarifs", "faq", "politique", etc.
    chunks_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid4())


class KnowledgeBase:
    """Base de connaissances métier persistée pour un business.

    Chaque business a sa propre base (isolation par business_id).
    Toutes les opérations passent par une session SQLAlchemy injectée.

    Usage (dans une route avec DbSession) :
        kb = KnowledgeBase(business_id=bid, session=db)
        await kb.add_text(content="Ouvert du lundi au samedi 9h-19h.", category="horaires")
        entries = await kb.list_entries()
    """

    def __init__(
        self,
        business_id: UUID | str,
        session: AsyncSession,
        embedder: BaseEmbedder | None = None,
        vector_store: PgVectorStore | None = None,
        ingester: DocumentIngester | None = None,
    ) -> None:
        self.business_id = str(business_id)
        self.session = session
        self.embedder = embedder or get_default_embedder()
        self.vector_store = vector_store or PgVectorStore(embedding_dim=self.embedder.dimension)
        self.ingester = ingester or DocumentIngester(embedder=self.embedder)

    def _require_pgvector(self) -> None:
        """Échoue vite sans Postgres."""
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            raise RuntimeError(f"pgvector indisponible (base {bind.dialect.name})")

    async def prepare_chunks(
        self,
        content: str,
        *,
        knowledge_id: str,
        title: str,
        category: str,
        source: str,
        extra_metadata: dict | None = None,
    ) -> list[dict]:
        """Découpe et vectorise, sans écrire."""
        # avant de charger le modèle
        self._require_pgvector()
        prepare = getattr(self.embedder, "prepare", None)
        if prepare is not None:
            await prepare()
        header = embed_header(title, category)
        # même repli que le découpage
        reserved = (self.ingester.count_tokens(header) + 1) if header else 0
        chunks = self.ingester.chunk_text(content, reserved_tokens=reserved)
        if not chunks:
            return []

        # titre + catégorie embarqués
        texts = [build_embed_text(c.content, title, category) for c in chunks]
        embed = getattr(self.embedder, "embed_passages", None) or self.embedder.embed_batch
        embeddings = await embed(texts)

        chunk_dicts: list[dict] = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
            # section / overlap du découpage
            layout = {
                k: chunk.metadata[k]
                for k in ("section", "overlap_chars", "sep")
                if k in chunk.metadata
            }
            chunk_dicts.append(
                {
                    "content": chunk.content,
                    "embedding": embedding,
                    "source": source,
                    "chunk_index": i,
                    "metadata": {
                        "knowledge_id": knowledge_id,
                        "title": title,
                        "category": category,
                        "source": source,
                        **layout,
                        **(extra_metadata or {}),
                    },
                }
            )
        return chunk_dicts

    async def _ingest(
        self,
        content: str,
        *,
        knowledge_id: str,
        title: str,
        category: str,
        source: str,
        extra_metadata: dict | None = None,
    ) -> int:
        """Découpe, vectorise et persiste. Renvoie le nb de chunks."""
        chunk_dicts = await self.prepare_chunks(
            content,
            knowledge_id=knowledge_id,
            title=title,
            category=category,
            source=source,
            extra_metadata=extra_metadata,
        )
        if not chunk_dicts:
            return 0
        count = await self.vector_store.add_chunks(self.session, self.business_id, chunk_dicts)
        await self.session.commit()
        return count

    async def add_text(
        self,
        content: str,
        title: str = "",
        category: str = "general",
        metadata: dict | None = None,
    ) -> KnowledgeEntry:
        """Ajoute du texte libre à la base de connaissances."""
        entry = KnowledgeEntry(
            business_id=self.business_id,
            title=title,
            content=content,
            source="text",
            category=category,
            metadata=metadata or {},
        )
        entry.chunks_count = await self._ingest(
            content,
            knowledge_id=entry.id,
            title=title,
            category=category,
            source="text",
            extra_metadata=metadata,
        )
        logger.info(
            "knowledge.text_added",
            id=entry.id[:8],
            category=category,
            chunks=entry.chunks_count,
            business_id=self.business_id,
        )
        return entry

    async def add_pdf(
        self,
        file_content: bytes,
        filename: str,
        title: str = "",
        category: str = "general",
        metadata: dict | None = None,
    ) -> KnowledgeEntry:
        """Ajoute un fichier PDF à la base de connaissances."""
        from jenny.rag.pdf_loader import PDFLoader

        loader = PDFLoader()
        pdf_doc = loader.load_bytes(file_content, filename)
        full_text = pdf_doc.full_text
        if not full_text.strip():
            raise ValueError(f"Le PDF '{filename}' ne contient pas de texte extractible.")

        preview = full_text[:500] + "..." if len(full_text) > 500 else full_text
        entry = KnowledgeEntry(
            business_id=self.business_id,
            title=title or filename,
            content=preview,
            source="pdf",
            category=category,
            metadata={
                "filename": filename,
                "total_pages": pdf_doc.total_pages,
                **(metadata or {}),
            },
        )
        entry.chunks_count = await self._ingest(
            full_text,
            knowledge_id=entry.id,
            title=title or filename,
            category=category,
            source="pdf",
            extra_metadata={"filename": filename},
        )
        logger.info(
            "knowledge.pdf_added",
            id=entry.id[:8],
            filename=filename,
            pages=pdf_doc.total_pages,
            chunks=entry.chunks_count,
            business_id=self.business_id,
        )
        return entry

    async def list_entries(self) -> list[KnowledgeEntry]:
        """Entrées avec leur texte complet."""
        rows = await self.vector_store.list_entries(self.session, self.business_id)
        entries: list[KnowledgeEntry] = []
        for r in rows:
            entries.append(
                KnowledgeEntry(
                    id=r["knowledge_id"],
                    business_id=self.business_id,
                    title=r["title"],
                    # texte entier, pas le 1er fragment
                    content=r.get("content") or r["preview"],
                    source=r["source"],
                    category=r["category"],
                    chunks_count=r["chunks_count"],
                    created_at=r["created_at"] or datetime.now(UTC),
                )
            )
        return entries

    async def get_entry(self, knowledge_id: str) -> KnowledgeEntry | None:
        """Une entrée, texte complet."""
        chunks = await self.vector_store.entry_chunks(self.session, self.business_id, knowledge_id)
        if not chunks:
            return None
        meta = chunks[0][1]
        return KnowledgeEntry(
            id=knowledge_id,
            business_id=self.business_id,
            title=meta.get("title") or "",
            content=reassemble(chunks),
            source=meta.get("source") or "text",
            category=meta.get("category") or "general",
            chunks_count=len(chunks),
            metadata={k: v for k, v in meta.items() if k not in LAYOUT_KEYS},
        )

    async def delete_entry(self, knowledge_id: str) -> bool:
        """Supprime une entrée (tous ses chunks) de la base de connaissances."""
        count = await self.vector_store.delete_by_knowledge_id(
            self.session, self.business_id, knowledge_id
        )
        await self.session.commit()
        return count > 0

    async def update_text_entry(
        self,
        knowledge_id: str,
        content: str,
        title: str = "",
        category: str = "general",
        metadata: dict | None = None,
    ) -> KnowledgeEntry | None:
        """Remplace le texte, même knowledge_id (None si absente)."""
        self._require_pgvector()
        current = await self.get_entry(knowledge_id)
        if current is None:
            return None
        # aperçu tronqué renvoyé tel quel
        fixed = restore_preview_tail(content, current.content)
        if fixed != content:
            logger.warning(
                "knowledge.update.tail_restored",
                id=knowledge_id[:8],
                sent=len(content),
                kept=len(fixed),
                business_id=self.business_id,
            )
            content = fixed
        # garde kb_key, filename...
        extra = {**current.metadata, **(metadata or {})}
        # vectorise avant d'effacer
        chunk_dicts = await self.prepare_chunks(
            content,
            knowledge_id=knowledge_id,
            title=title,
            category=category,
            source="text",
            extra_metadata=extra,
        )
        deleted = await self.vector_store.delete_by_knowledge_id(
            self.session, self.business_id, knowledge_id
        )
        if deleted == 0:
            await self.session.rollback()
            return None
        count = 0
        if chunk_dicts:
            count = await self.vector_store.add_chunks(self.session, self.business_id, chunk_dicts)
        await self.session.commit()
        entry = KnowledgeEntry(
            id=knowledge_id,
            business_id=self.business_id,
            title=title,
            content=content,
            source="text",
            category=category,
            chunks_count=count,
            metadata=extra,
        )
        logger.info(
            "knowledge.entry_updated",
            id=knowledge_id[:8],
            chunks=entry.chunks_count,
            business_id=self.business_id,
        )
        return entry

    async def stats(self) -> dict:
        """Statistiques de la base de connaissances du business."""
        entries = await self.list_entries()
        by_category: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for e in entries:
            by_category[e.category] = by_category.get(e.category, 0) + 1
            by_source[e.source] = by_source.get(e.source, 0) + 1
        return {
            "business_id": self.business_id,
            "total_entries": len(entries),
            "total_chunks": sum(e.chunks_count for e in entries),
            "by_category": by_category,
            "by_source": by_source,
        }

    async def search(self, query: str, top_k: int = 3, score_threshold: float = 0.0) -> list[dict]:
        """Recherche hybride, même chemin que le chat."""
        if self.session.get_bind().dialect.name != "postgresql":
            # pas de pgvector ici
            return []
        embedding = await embed_query(self.embedder, query)
        docs = await self.vector_store.search(
            self.session,
            self.business_id,
            embedding,
            top_k=top_k,
            score_threshold=score_threshold,
            query_text=query,
        )
        return [{"content": d.content, "score": d.score, "metadata": d.metadata} for d in docs]
