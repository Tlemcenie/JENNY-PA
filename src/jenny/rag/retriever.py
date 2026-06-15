"""Retriever pour le RAG (Retrieval-Augmented Generation).

Recherche dans la base vectorielle (pgvector) les chunks les plus
pertinents — scopés par business — pour enrichir le contexte du LLM.

Pipeline :
1. Encoder la requête en embedding
2. Rechercher les chunks similaires dans document_embeddings (par business)
3. Retourner les documents pertinents

Le retriever ouvre sa propre session DB courte (via le session factory)
car le moteur conversationnel ne transporte pas de session.
"""

from __future__ import annotations

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


class VectorRetriever:
    """Retriever sémantique basé sur pgvector, scopé par business.

    Combine un embedder (encode la requête) et un vector store (recherche
    de similarité) en un composant utilisable par les agents.
    """

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
        """Recherche les chunks les plus pertinents pour une requête.

        Args:
            query: Texte de la requête utilisateur.
            business_id: Business propriétaire de la base de connaissances.
            top_k: Nombre maximum de résultats.
            score_threshold: Score minimum de similarité (cosinus).

        Returns:
            Documents triés par pertinence décroissante.
        """
        if self.embedder is None or self.vector_store is None or business_id is None:
            return []

        try:
            query_embedding = await self.embedder.embed_text(query)
        except Exception as e:
            logger.warning("retriever.embed_error", error=str(e))
            return []

        factory = self._get_session_factory()
        async with factory() as session:
            stored = await self.vector_store.search(
                session=session,
                business_id=business_id,
                query_embedding=query_embedding,
                top_k=top_k,
                score_threshold=score_threshold,
            )

        results = [
            RetrievedDocument(
                id=doc.id,
                content=doc.content,
                score=doc.score,
                metadata=doc.metadata,
            )
            for doc in stored
        ]
        logger.info("retriever.search", results=len(results), business_id=str(business_id))
        return results
