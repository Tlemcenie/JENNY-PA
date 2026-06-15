"""Service d'embeddings pour le RAG.

Gère la génération de vecteurs d'embedding à partir de texte
pour l'indexation et la recherche sémantique.

Supporte plusieurs backends :
- Ollama (nomic-embed-text, 768-dim) — local, gratuit, par défaut
- Sentence Transformers (all-MiniLM-L6-v2, 384-dim) — local
- OpenAI (text-embedding-3-small, 1536-dim)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from jenny.core.logging import get_logger

logger = get_logger(__name__)


class BaseEmbedder(ABC):
    """Interface pour les services d'embedding."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimension des vecteurs produits."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Génère un embedding pour un texte."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Génère des embeddings pour un batch de textes.

        Implémentation par défaut séquentielle.
        Les sous-classes peuvent optimiser avec du batching natif.
        """
        return [await self.embed_text(text) for text in texts]


class SentenceTransformerEmbedder(BaseEmbedder):
    """Embeddings via Sentence Transformers (local, gratuit).

    Utilise all-MiniLM-L6-v2 (384 dimensions) par défaut.
    Parfait pour le développement local et les petits volumes.
    Fonctionne sur M1 Pro via MPS.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        self.model_name = model_name
        self._model = None
        self._dimension = 384  # Défaut pour MiniLM

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_model(self) -> None:
        """Charge le modèle Sentence Transformer (lazy loading)."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info(
                    "embedder.sentence_transformer.loaded",
                    model=self.model_name,
                    dim=self._dimension,
                )
            except ImportError:
                logger.warning(
                    "embedder.sentence_transformer.not_installed",
                    hint="pip install sentence-transformers",
                )
                raise

    async def embed_text(self, text: str) -> list[float]:
        """Génère un embedding local via Sentence Transformers."""
        self._load_model()
        assert self._model is not None
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch d'embeddings via Sentence Transformers (optimisé)."""
        self._load_model()
        assert self._model is not None
        embeddings = self._model.encode(texts, convert_to_numpy=True, batch_size=32)
        return embeddings.tolist()


class OpenAIEmbedder(BaseEmbedder):
    """Embeddings via l'API OpenAI.

    Utilise le modèle text-embedding-3-small (1536 dimensions).
    Nécessite une clé API OpenAI.
    """

    def __init__(self, api_key: str | None = None) -> None:
        import os

        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._dimension = 1536

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        """Génère un embedding via l'API OpenAI."""
        if not self.api_key:
            logger.warning("embedder.openai.no_api_key")
            return [0.0] * self._dimension

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "text-embedding-3-small",
                        "input": text,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            logger.error("embedder.openai.error", error=str(e))
            return [0.0] * self._dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch d'embeddings via OpenAI (une seule requête API)."""
        if not self.api_key:
            return [[0.0] * self._dimension for _ in texts]

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "text-embedding-3-small",
                        "input": texts,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                return [item["embedding"] for item in data["data"]]
        except Exception as e:
            logger.error("embedder.openai.batch_error", error=str(e))
            return [[0.0] * self._dimension for _ in texts]


class OllamaEmbedder(BaseEmbedder):
    """Embeddings via Ollama (local, gratuit, sans clé API).

    Utilise nomic-embed-text (768 dimensions) par défaut, performant
    en multilingue (dont le français). Appelle l'API HTTP locale d'Ollama.
    """

    # Dimensions connues des modèles Ollama courants
    _KNOWN_DIMS: ClassVar[dict[str, int]] = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "bge-m3": 1024,
    }

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        dimension: int | None = None,
        keep_alive: str = "30m",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Garde le modèle d'embedding chargé entre les requêtes (anti cold-start).
        self.keep_alive = keep_alive
        base = model.split(":")[0]
        self._dimension = dimension or self._KNOWN_DIMS.get(base, 768)

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        """Génère un embedding via l'API Ollama (/api/embeddings)."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text, "keep_alive": self.keep_alive},
                timeout=60.0,
            )
            response.raise_for_status()
            embedding = response.json()["embedding"]
        # Ajuste la dimension cache si différente (premier appel fiable)
        self._dimension = len(embedding)
        return embedding


# ── Factory ──


def get_embedder(backend: str = "ollama", **kwargs) -> BaseEmbedder:
    """Factory pour créer un embedder.

    Args:
        backend: "ollama" (défaut, local), "sentence-transformer" (local)
            ou "openai" (API).

    Returns:
        Instance de l'embedder.
    """
    if backend == "ollama":
        return OllamaEmbedder(**kwargs)
    if backend == "openai":
        return OpenAIEmbedder(**kwargs)
    if backend == "sentence-transformer":
        return SentenceTransformerEmbedder(**kwargs)
    raise ValueError(
        f"Backend inconnu : {backend}. Options : ollama, sentence-transformer, openai"
    )


def get_default_embedder() -> BaseEmbedder:
    """Construit l'embedder configuré dans les Settings (.env)."""
    from jenny.core.config import get_settings

    settings = get_settings()
    backend = settings.embeddings_backend
    if backend == "ollama":
        return OllamaEmbedder(
            model=settings.embeddings_model,
            base_url=settings.llama_base_url,
            keep_alive=settings.llama_keep_alive,
        )
    if backend == "sentence-transformer":
        return SentenceTransformerEmbedder(model_name=settings.embeddings_model)
    if backend == "openai":
        return OpenAIEmbedder()
    return OllamaEmbedder(
        model=settings.embeddings_model,
        base_url=settings.llama_base_url,
        keep_alive=settings.llama_keep_alive,
    )
