"""vector store en mémoire."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MemoryDocument:
    """doc en mémoire."""

    id: str
    content: str
    embedding: list[float]
    metadata: dict = field(default_factory=dict)
    collection: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class StoredDocument:
    """doc retourné par recherche."""

    id: str
    content: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)
    collection: str = "default"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """similarité cosinus."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    """store mémoire pour les tests."""

    def __init__(
        self,
        collection: str = "default",
        embedding_dim: int = 384,
    ) -> None:
        self.collection = collection
        self.embedding_dim = embedding_dim
        self._documents: list[MemoryDocument] = []

    @property
    def count(self) -> int:
        """nb de documents."""
        return len([d for d in self._documents if d.collection == self.collection])

    async def add_document(
        self,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
        **kwargs,
    ) -> str:
        """ajoute un document."""
        doc_id = str(uuid4())
        doc = MemoryDocument(
            id=doc_id,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            collection=self.collection,
        )
        self._documents.append(doc)
        logger.info("memory_store.added", doc_id=doc_id[:8])
        return doc_id

    async def add_documents(
        self,
        documents: list[dict],
        **kwargs,
    ) -> list[str]:
        """ajout en batch."""
        ids = []
        for doc in documents:
            doc_id = await self.add_document(
                content=doc["content"],
                embedding=doc["embedding"],
                metadata=doc.get("metadata", {}),
            )
            ids.append(doc_id)
        logger.info("memory_store.batch_added", count=len(ids))
        return ids

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
        **kwargs,
    ) -> list[StoredDocument]:
        """recherche cosinus."""
        collection_docs = [d for d in self._documents if d.collection == self.collection]

        if not collection_docs:
            return []

        # calcule les scores
        scored = []
        for doc in collection_docs:
            score = _cosine_similarity(query_embedding, doc.embedding)
            if score >= score_threshold:
                scored.append((doc, score))

        # tri décroissant
        scored.sort(key=lambda x: x[1], reverse=True)

        # coupe au top_k
        results = []
        for doc, score in scored[:top_k]:
            results.append(
                StoredDocument(
                    id=doc.id,
                    content=doc.content,
                    score=score,
                    metadata=doc.metadata,
                    collection=doc.collection,
                )
            )

        logger.info(
            "memory_store.search",
            results=len(results),
            top_score=f"{results[0].score:.4f}" if results else "N/A",
        )
        return results

    async def delete_document(self, doc_id: str, **kwargs) -> bool:
        """supprime par id."""
        before = len(self._documents)
        self._documents = [d for d in self._documents if d.id != doc_id]
        return len(self._documents) < before

    async def delete_collection(self, **kwargs) -> int:
        """vide la collection."""
        before = len(self._documents)
        self._documents = [d for d in self._documents if d.collection != self.collection]
        count = before - len(self._documents)
        logger.info("memory_store.collection_deleted", count=count)
        return count

    def clear(self) -> None:
        """vide tout."""
        self._documents.clear()
