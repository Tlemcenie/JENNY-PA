"""vector store pgvector (recherche hybride)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import text

from jenny.core.logging import get_logger
from jenny.rag import rerank as _rr
from jenny.rag.ingestion import reassemble
from jenny.rag.lexique import STOPWORDS, expansions, fold

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# candidats par voie (repli)
POOL_SIZE = 30
# ordre final : "mix", "rrf" ou "score"
FUSION = "mix"
# config FR sans accents
TS_CONFIG = "jenny_fr"
# capacités revues toutes les 5 min
_CAPS_TTL = 300.0
_TSQ_WORD_RE = re.compile(r"^[a-z0-9]+$")
# mots accentués (config french)
_RAW_WORD_RE = re.compile(r"[^\W\d_]{3,}")


class VectorSearchError(RuntimeError):
    """Échec de la recherche pgvector."""


def default_pool() -> int:
    """Candidats par voie (réglage)."""
    from jenny.core.config import get_settings

    try:
        n = int(get_settings().rag_rerank_candidates)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else POOL_SIZE


@dataclass
class StoredDocument:
    """chunk retrouvé."""

    id: str
    content: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)
    source: str | None = None
    created_at: datetime | None = None
    vector_score: float = 0.0
    lexical_score: float = 0.0
    fused: float = 0.0


def _vector_literal(embedding: list[float]) -> str:
    """format littéral pgvector."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _parse_meta(meta) -> dict:
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    return meta if isinstance(meta, dict) else {}


def _with_index(contents, metas, idx) -> list[tuple[str, dict]]:
    """(texte, meta) avec leur rang."""
    metas = list(metas or [])
    idx = list(idx or [])
    out: list[tuple[str, dict]] = []
    for pos, content in enumerate(contents):
        meta = _parse_meta(metas[pos] if pos < len(metas) else None)
        rank = idx[pos] if pos < len(idx) and idx[pos] is not None else pos
        out.append((content or "", {**meta, "chunk_index": rank}))
    return out


def build_tsquery(query: str, max_terms: int = 40, keep_accents: bool = False) -> str:
    """Requête OR (mots + synonymes)."""
    words = [w for w in (fold(x) for x in expansions(query)) if _TSQ_WORD_RE.match(w)]
    if keep_accents:
        # index sans unaccent
        raw = [w for w in _RAW_WORD_RE.findall((query or "").lower()) if fold(w) not in STOPWORDS]
        words = list(dict.fromkeys([*raw, *words]))
    return " | ".join(words[:max_terms])


@dataclass
class _Caps:
    postgres: bool
    fts: bool = False
    ts_config: str = "french"
    iterative: bool = False
    at: float = 0.0


_CAPS: dict[str, _Caps] = {}

# verrous consultatifs de la KB
_LOCK_SQL = "SELECT {fn}(hashtextextended(:key, 0))"


def _is_pg(session: AsyncSession) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


async def lock_entry(session: AsyncSession, business_id: UUID | str, knowledge_id: str) -> bool:
    """Verrou d'une entrée, jusqu'au commit."""
    if not _is_pg(session):
        return False
    # salon partagé, puis l'entrée
    await session.execute(
        text(_LOCK_SQL.format(fn="pg_advisory_xact_lock_shared")),
        {"key": f"jenny:kb:{business_id}"},
    )
    await session.execute(
        text(_LOCK_SQL.format(fn="pg_advisory_xact_lock")),
        {"key": f"jenny:kb:{business_id}:{knowledge_id}"},
    )
    return True


async def lock_business_kb(session: AsyncSession, business_id: UUID | str) -> bool:
    """Verrou de toute la KB d'un salon."""
    if not _is_pg(session):
        return False
    await session.execute(
        text(_LOCK_SQL.format(fn="pg_advisory_xact_lock")),
        {"key": f"jenny:kb:{business_id}"},
    )
    return True


class PgVectorStore:
    """store pgvector scopé par business."""

    def __init__(self, embedding_dim: int = 768) -> None:
        self.embedding_dim = embedding_dim

    async def _caps(self, session: AsyncSession) -> _Caps:
        """Ce que la base sait faire."""
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return _Caps(postgres=False)
        key = str(bind.url)
        cached = _CAPS.get(key)
        if cached is not None and time.monotonic() - cached.at < _CAPS_TTL:
            return cached
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'document_embeddings'
                          AND column_name = 'content_tsv'
                      ) AS fts,
                      EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = :cfg) AS cfg,
                      (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vver
                    """
                ),
                {"cfg": TS_CONFIG},
            )
        ).one()
        vver = tuple(int(p) for p in re.findall(r"\d+", row.vver or "0")[:2])
        caps = _Caps(
            postgres=True,
            fts=bool(row.fts),
            ts_config=TS_CONFIG if row.cfg else "french",
            iterative=vver >= (0, 8),
            at=time.monotonic(),
        )
        _CAPS[key] = caps
        return caps

    async def add_chunks(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        chunks: list[dict],
    ) -> int:
        """insère des chunks."""
        inserted = 0
        for c in chunks:
            embedding = c.get("embedding")
            if embedding is None:
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO document_embeddings
                        (business_id, content, source, chunk_index, metadata_, embedding,
                         created_at)
                    VALUES
                        (:business_id, :content, :source, :chunk_index,
                         CAST(:metadata AS json), CAST(:embedding AS vector),
                         COALESCE(:created_at, now()))
                    """
                ),
                {
                    "business_id": str(business_id),
                    "content": c.get("content", ""),
                    "source": c.get("source"),
                    "chunk_index": c.get("chunk_index"),
                    "metadata": json.dumps(c.get("metadata") or {}, ensure_ascii=False),
                    "embedding": _vector_literal(embedding),
                    # garde la date (réindex)
                    "created_at": c.get("created_at"),
                },
            )
            inserted += 1

        logger.info("vector_store.added", business_id=str(business_id), count=inserted)
        return inserted

    async def search(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
        query_text: str | None = None,
        pool_size: int | None = None,
    ) -> list[StoredDocument]:
        """Recherche hybride, seuil puis top_k."""
        try:
            caps = await self._caps(session)
        except Exception as e:
            logger.error("vector_store.caps.error", error=str(e), exc_info=True)
            # pas de SQL dans l'erreur
            raise VectorSearchError(type(e).__name__) from e
        if not caps.postgres:
            logger.debug("vector_store.search.no_pgvector", business_id=str(business_id))
            return []

        pool = max(pool_size or default_pool(), top_k)
        tsq = ""
        if query_text and caps.fts:
            tsq = build_tsquery(query_text, keep_accents=caps.ts_config != TS_CONFIG)
        params = {
            "embedding": _vector_literal(query_embedding),
            "business_id": str(business_id),
            "pool": pool,
        }
        if tsq:
            params["tsq"] = tsq
            sql = f"""
                WITH vec AS (
                    SELECT id FROM document_embeddings
                    WHERE business_id = :business_id AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :pool
                ),
                fts AS (
                    SELECT id, ts_rank_cd(content_tsv, q) AS trank
                    FROM document_embeddings,
                         to_tsquery('{caps.ts_config}', :tsq) AS q
                    WHERE business_id = :business_id AND content_tsv @@ q
                    ORDER BY trank DESC
                    LIMIT :pool
                )
                SELECT d.id, d.content, d.source, d.metadata_, d.created_at,
                       1 - (d.embedding <=> CAST(:embedding AS vector)) AS vscore,
                       fts.trank AS trank
                FROM document_embeddings d
                LEFT JOIN fts ON fts.id = d.id
                WHERE d.business_id = :business_id
                  AND d.id IN (SELECT id FROM vec UNION SELECT id FROM fts)
            """
        else:
            sql = """
                SELECT id, content, source, metadata_, created_at,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS vscore,
                       NULL AS trank
                FROM document_embeddings
                WHERE business_id = :business_id AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :pool
            """
        try:
            if caps.iterative:
                # filtre business sans perte
                await session.execute(
                    text(
                        "SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
                        "set_config('hnsw.ef_search', '100', true)"
                    )
                )
            rows = (await session.execute(text(sql), params)).fetchall()
        except Exception as e:
            logger.error(
                "vector_store.search.error",
                business_id=str(business_id),
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            # pas de SQL dans l'erreur
            raise VectorSearchError(type(e).__name__) from e

        docs = self._fuse(rows, query_text or "")
        kept = [d for d in docs if d.score >= score_threshold]
        logger.info(
            "vector_store.search",
            business_id=str(business_id),
            candidates=len(docs),
            kept=len(kept),
            hybrid=bool(tsq),
            top_score=round(max(d.score for d in kept), 3) if kept else None,
        )
        return kept[:top_k]

    @staticmethod
    def _fuse(rows, query_text: str) -> list[StoredDocument]:
        """Score blendé + ordre RRF."""
        from jenny.core.config import get_settings

        use_lex = bool(query_text) and get_settings().rag_rerank
        docs: list[StoredDocument] = []
        tranks: dict[str, float] = {}
        for row in rows:
            meta = _parse_meta(row.metadata_)
            vscore = float(row.vscore) if row.vscore is not None else 0.0
            lex = (
                _rr.lexical_score(query_text, row.content or "", meta.get("title") or "")
                if use_lex
                else 0.0
            )
            doc = StoredDocument(
                id=str(row.id),
                content=row.content,
                metadata=meta,
                source=row.source,
                created_at=getattr(row, "created_at", None),
                vector_score=vscore,
                lexical_score=lex,
                score=_rr.blend(vscore, lex) if use_lex else vscore,
            )
            docs.append(doc)
            if row.trank is not None:
                tranks[doc.id] = float(row.trank)

        by_vec = [d.id for d in sorted(docs, key=lambda d: d.vector_score, reverse=True)]
        rankings = [by_vec]
        if tranks:
            rankings.append(sorted(tranks, key=lambda i: tranks[i], reverse=True))
        if use_lex:
            lex_ranked = sorted(
                (d for d in docs if d.lexical_score > 0),
                key=lambda d: d.lexical_score,
                reverse=True,
            )
            rankings.append([d.id for d in lex_ranked])
        fused = _rr.rrf(rankings)
        for d in docs:
            d.fused = fused.get(d.id, 0.0)
        top = max((d.fused for d in docs), default=0.0)
        docs.sort(key=lambda d: _rr.fusion_key(d.score, d.fused, top, FUSION), reverse=True)
        return docs

    async def list_entries(
        self,
        session: AsyncSession,
        business_id: UUID | str,
    ) -> list[dict]:
        """Entrées groupées, texte recollé."""
        result = await session.execute(
            text(
                """
                SELECT
                    metadata_->>'knowledge_id' AS knowledge_id,
                    max(metadata_->>'title')    AS title,
                    max(metadata_->>'category') AS category,
                    max(metadata_->>'source')   AS source,
                    array_agg(content ORDER BY chunk_index, id) AS contents,
                    array_agg(metadata_::text ORDER BY chunk_index, id) AS metas,
                    array_agg(chunk_index ORDER BY chunk_index, id) AS idx,
                    count(*)        AS chunks_count,
                    min(created_at) AS created_at
                FROM document_embeddings
                WHERE business_id = :business_id
                  AND metadata_->>'knowledge_id' IS NOT NULL
                GROUP BY metadata_->>'knowledge_id'
                ORDER BY min(created_at) DESC
                """
            ),
            {"business_id": str(business_id)},
        )
        entries: list[dict] = []
        for row in result.fetchall():
            contents = list(row.contents or [])
            chunks = _with_index(contents, row.metas, row.idx)
            entries.append(
                {
                    "knowledge_id": row.knowledge_id,
                    "title": row.title or "",
                    "category": row.category or "general",
                    "source": row.source or "text",
                    # 1er fragment seul
                    "preview": (contents[0] if contents else "") or "",
                    # texte complet à éditer
                    "content": reassemble(chunks),
                    # méta du 1er fragment
                    "metadata": chunks[0][1] if chunks else {},
                    "chunks_count": int(row.chunks_count),
                    "created_at": row.created_at,
                }
            )
        return entries

    async def entry_chunks(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        knowledge_id: str,
    ) -> list[tuple[str, dict]]:
        """Fragments d'une entrée, dans l'ordre."""
        result = await session.execute(
            text(
                """
                SELECT content, metadata_, chunk_index
                FROM document_embeddings
                WHERE business_id = :business_id
                  AND metadata_->>'knowledge_id' = :knowledge_id
                ORDER BY chunk_index, id
                """
            ),
            {"business_id": str(business_id), "knowledge_id": knowledge_id},
        )
        rows = result.fetchall()
        return _with_index(
            [r.content for r in rows], [r.metadata_ for r in rows], [r.chunk_index for r in rows]
        )

    async def delete_by_knowledge_id(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        knowledge_id: str,
    ) -> int:
        """supprime une entrée."""
        result = await session.execute(
            text(
                """
                DELETE FROM document_embeddings
                WHERE business_id = :business_id
                  AND metadata_->>'knowledge_id' = :knowledge_id
                """
            ),
            {"business_id": str(business_id), "knowledge_id": knowledge_id},
        )
        count = result.rowcount or 0
        logger.info(
            "vector_store.deleted",
            business_id=str(business_id),
            knowledge_id=knowledge_id,
            chunks=count,
        )
        return count
