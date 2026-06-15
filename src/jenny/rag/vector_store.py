"""Vector Store — Stockage et recherche via pgvector.

Persiste les chunks de documents dans la table `document_embeddings`
(PostgreSQL + extension pgvector) et effectue la recherche de similarité
cosinus, scopée par business.

Schéma (créé via Alembic, voir migrations/versions) :
    CREATE TABLE document_embeddings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id UUID NOT NULL REFERENCES businesses(id),
        content TEXT NOT NULL,
        source VARCHAR(500),
        chunk_index INTEGER,
        metadata_ JSON,
        embedding vector(768),
        created_at TIMESTAMPTZ
    );
    CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops);
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import text

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass
class StoredDocument:
    """Document (chunk) retrouvé dans le vector store."""

    id: str
    content: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)
    source: str | None = None
    created_at: datetime | None = None


def _vector_literal(embedding: list[float]) -> str:
    """Sérialise un vecteur Python au format littéral pgvector ('[1,2,3]')."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PgVectorStore:
    """Store vectoriel basé sur PostgreSQL + pgvector (table document_embeddings).

    Toutes les opérations sont scopées par `business_id` (isolation multi-tenant)
    et nécessitent une `AsyncSession` injectée par l'appelant.
    """

    def __init__(self, embedding_dim: int = 768) -> None:
        self.embedding_dim = embedding_dim

    async def add_chunks(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        chunks: list[dict],
    ) -> int:
        """Insère des chunks (content + embedding + metadata) pour un business.

        Args:
            session: Session SQLAlchemy (le commit est géré par l'appelant).
            business_id: Business propriétaire des chunks.
            chunks: Liste de dicts {content, embedding, source?, chunk_index?, metadata?}.

        Returns:
            Nombre de chunks insérés.
        """
        inserted = 0
        for c in chunks:
            embedding = c.get("embedding")
            if embedding is None:
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO document_embeddings
                        (business_id, content, source, chunk_index, metadata_, embedding)
                    VALUES
                        (:business_id, :content, :source, :chunk_index,
                         CAST(:metadata AS json), CAST(:embedding AS vector))
                    """
                ),
                {
                    "business_id": str(business_id),
                    "content": c.get("content", ""),
                    "source": c.get("source"),
                    "chunk_index": c.get("chunk_index"),
                    "metadata": json.dumps(c.get("metadata") or {}, ensure_ascii=False),
                    "embedding": _vector_literal(embedding),
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
    ) -> list[StoredDocument]:
        """Recherche les chunks les plus proches (cosinus) pour un business."""
        embedding = _vector_literal(query_embedding)
        try:
            result = await session.execute(
                text(
                    """
                    SELECT id, content, source, metadata_,
                           1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM document_embeddings
                    WHERE business_id = :business_id
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :top_k
                    """
                ),
                {
                    "embedding": embedding,
                    "business_id": str(business_id),
                    "top_k": top_k,
                },
            )
        except Exception as e:
            logger.error("vector_store.search.error", error=str(e))
            return []

        docs: list[StoredDocument] = []
        for row in result.fetchall():
            score = float(row.score) if row.score is not None else 0.0
            if score < score_threshold:
                continue
            meta = row.metadata_
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            docs.append(
                StoredDocument(
                    id=str(row.id),
                    content=row.content,
                    score=score,
                    metadata=meta or {},
                    source=row.source,
                )
            )
        logger.info("vector_store.search", business_id=str(business_id), results=len(docs))
        return docs

    async def list_entries(
        self,
        session: AsyncSession,
        business_id: UUID | str,
    ) -> list[dict]:
        """Liste les entrées logiques (groupées par knowledge_id)."""
        result = await session.execute(
            text(
                """
                SELECT
                    metadata_->>'knowledge_id' AS knowledge_id,
                    max(metadata_->>'title')    AS title,
                    max(metadata_->>'category') AS category,
                    max(metadata_->>'source')   AS source,
                    (array_agg(content ORDER BY chunk_index))[1] AS preview,
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
            entries.append(
                {
                    "knowledge_id": row.knowledge_id,
                    "title": row.title or "",
                    "category": row.category or "general",
                    "source": row.source or "text",
                    "preview": row.preview or "",
                    "chunks_count": int(row.chunks_count),
                    "created_at": row.created_at,
                }
            )
        return entries

    async def delete_by_knowledge_id(
        self,
        session: AsyncSession,
        business_id: UUID | str,
        knowledge_id: str,
    ) -> int:
        """Supprime tous les chunks d'une entrée logique."""
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
