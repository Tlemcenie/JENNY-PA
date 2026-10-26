"""Retriever RAG hybride, scopé par business.

1. Encode la question
2. Recherche hybride pgvector + texte intégral (RRF)
3. Seuil sur le score blendé, puis top_k

Ouvre sa propre session courte (le moteur n'en transporte pas).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    from jenny.rag.embeddings import BaseEmbedder
    from jenny.rag.vector_store import PgVectorStore

logger = get_logger(__name__)


@dataclass
class RetrievedDocument:
    """Document récupéré depuis la base vectorielle."""

    id: str
    content: str
    score: float
    metadata: dict


def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


async def embed_query(embedder, query: str) -> list[float]:
    """Embedding de question (préfixe/cache)."""
    fn = getattr(embedder, "embed_query", None)
    if fn is not None:
        return await fn(query)
    return await embedder.embed_text(query)


class VectorRetriever:
    """Retriever hybride (embedder + store pgvector)."""

    def __init__(
        self,
        embedder: BaseEmbedder | None = None,
        vector_store: PgVectorStore | None = None,
        session_factory: object | None = None,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self._session_factory = session_factory

    def _get_session_factory(self):
        if self._session_factory is None:
            from jenny.db.session import async_session_factory

            self._session_factory = async_session_factory
        return self._session_factory

    async def search(
        self,
        query: str,
        business_id: UUID | str | None,
        top_k: int = 3,
        score_threshold: float = 0.0,
    ) -> list[RetrievedDocument]:
        """Chunks pertinents, triés, au-dessus du seuil."""
        if self.embedder is None or self.vector_store is None or business_id is None:
            return []

        try:
            query_embedding = await embed_query(self.embedder, query)
        except Exception as e:
            logger.warning("retriever.embed_error", error=str(e))
            return []

        hybrid = _accepts(self.vector_store.search, "query_text")
        kwargs: dict = {
            "business_id": business_id,
            "query_embedding": query_embedding,
            "top_k": top_k,
            "score_threshold": score_threshold,
        }
        if hybrid:
            kwargs["query_text"] = query
        else:
            # vieux store : pool sans seuil
            from jenny.core.config import get_settings

            kwargs["top_k"] = max(top_k, get_settings().rag_rerank_candidates)
            kwargs["score_threshold"] = 0.0

        try:
            factory = self._get_session_factory()
            async with factory() as session:
                stored = await self.vector_store.search(session=session, **kwargs)
        except Exception as e:
            # le chat continue sans docs
            logger.error(
                "retriever.search_failed",
                business_id=str(business_id),
                error_type=type(e).__name__,
                error=str(e),
            )
            return []

        if not hybrid:
            # vieux store : blend ici
            from jenny.core.config import get_settings

            if get_settings().rag_rerank:
                from jenny.rag.rerank import rerank

                stored = rerank(query, list(stored), len(stored))
            stored = [d for d in stored if d.score >= score_threshold][:top_k]

        results = [
            RetrievedDocument(
                id=doc.id,
                content=doc.content,
                score=doc.score,
                metadata=doc.metadata,
            )
            for doc in stored
        ]
        logger.info(
            "retriever.search",
            results=len(results),
            top_score=round(results[0].score, 3) if results else None,
            business_id=str(business_id),
        )
        return results
