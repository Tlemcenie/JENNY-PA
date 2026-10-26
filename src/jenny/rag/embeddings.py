"""Embeddings pour le RAG."""

from __future__ import annotations

import copy
import math
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import ClassVar

from jenny.core.logging import get_logger

logger = get_logger(__name__)

# ~3,8 car./token mesuré en FR
_CHARS_PER_TOKEN = 3.4


def estimate_tokens(text: str) -> int:
    """Estimation prudente des tokens."""
    return math.ceil(len(text or "") / _CHARS_PER_TOKEN)


class BaseEmbedder(ABC):
    """Interface pour les services d'embedding."""

    # fenêtre du modèle (tokens)
    max_tokens: int = 512

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
        """Embeddings d'un lot, séquentiel par défaut."""
        return [await self.embed_text(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embedding d'une question."""
        return await self.embed_text(text)

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embeddings de passages à indexer."""
        return await self.embed_batch(texts)

    def count_tokens(self, text: str) -> int:
        """Nombre de tokens (estimé)."""
        return estimate_tokens(text)

    async def prepare(self) -> None:
        """Préchauffe le modèle si besoin."""
        return None


# modèles chargés, partagés
_ST_MODELS: dict[str, object] = {}
_ST_LOCK = threading.Lock()
# tokenizers à part, pour compter
_COUNT_TOKENIZERS: dict[str, tuple[object, object, bool]] = {}
_COUNT_LOCK = threading.Lock()
# copie ratée : on réessaie
_COPY_TRIES = 3


def _copy_tokenizer(tok) -> tuple[object, bool] | None:
    """Copie du tokenizer, sans le partager."""
    backend = getattr(tok, "backend_tokenizer", None)
    for _ in range(_COPY_TRIES):
        try:
            if backend is not None:
                from tokenizers import Tokenizer

                fresh = Tokenizer.from_str(backend.to_str())
                # réglé une fois, jamais modifié
                fresh.no_truncation()
                fresh.no_padding()
                return fresh, True
            return copy.deepcopy(tok), False
        except RuntimeError:
            # modèle en cours d'écriture
            time.sleep(0.01)
    return None


def _counting_tokenizer(model_name: str, model) -> tuple[object, bool] | None:
    """Tokenizer dédié au comptage."""
    hit = _COUNT_TOKENIZERS.get(model_name)
    # même modèle qu'à la copie
    if hit is not None and hit[0] is model:
        return hit[1], hit[2]
    tok = getattr(model, "tokenizer", None)
    if tok is None:
        return None
    with _COUNT_LOCK:
        hit = _COUNT_TOKENIZERS.get(model_name)
        if hit is not None and hit[0] is model:
            return hit[1], hit[2]
        got = _copy_tokenizer(tok)
        if got is not None:
            _COUNT_TOKENIZERS[model_name] = (model, *got)
    return got


def _load_st_model(model_name: str):
    """Charge un modèle une seule fois."""
    model = _ST_MODELS.get(model_name)
    if model is not None:
        return model
    with _ST_LOCK:
        model = _ST_MODELS.get(model_name)
        if model is not None:
            return model
        from sentence_transformers import SentenceTransformer

        try:
            # cache local d'abord
            model = SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            model = SentenceTransformer(model_name)
        _ST_MODELS[model_name] = model
        return model


def adopt_st_model(model_name: str, model: object) -> bool:
    """Partage un modèle déjà chargé."""
    with _ST_LOCK:
        if model_name in _ST_MODELS:
            return False
        _ST_MODELS[model_name] = model
        return True


class SentenceTransformerEmbedder(BaseEmbedder):
    """Embeddings locaux via Sentence Transformers."""

    # dims connues, sans charger
    _KNOWN_DIMS: ClassVar[dict[str, int]] = {
        "all-MiniLM-L6-v2": 384,
        "paraphrase-multilingual-MiniLM-L12-v2": 384,
        "paraphrase-multilingual-mpnet-base-v2": 768,
        "distiluse-base-multilingual-cased-v2": 512,
        "multilingual-e5-base": 768,
        "gte-multilingual-base": 768,
    }
    # fenêtres connues (tokens)
    _KNOWN_WINDOWS: ClassVar[dict[str, int]] = {
        "all-MiniLM-L6-v2": 256,
        "paraphrase-multilingual-MiniLM-L12-v2": 128,
        "paraphrase-multilingual-mpnet-base-v2": 128,
        "distiluse-base-multilingual-cased-v2": 128,
        "multilingual-e5-base": 512,
        "gte-multilingual-base": 8192,
    }
    # préfixes requis (e5)
    _PREFIXES: ClassVar[dict[str, tuple[str, str]]] = {
        "multilingual-e5-base": ("query: ", "passage: "),
        "multilingual-e5-small": ("query: ", "passage: "),
        "multilingual-e5-large": ("query: ", "passage: "),
    }
    _QUERY_CACHE_SIZE: ClassVar[int] = 256

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
    ) -> None:
        self.model_name = model_name
        base = model_name.split("/")[-1]
        self._dimension = self._KNOWN_DIMS.get(base, 768)
        self.max_tokens = self._KNOWN_WINDOWS.get(base, 128)
        self._query_prefix, self._passage_prefix = self._PREFIXES.get(base, ("", ""))
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def _model(self):
        """Modèle si déjà chargé."""
        return _ST_MODELS.get(self.model_name)

    def _load_model(self):
        """Charge le modèle (lazy, thread-safe)."""
        already = self._model is not None
        try:
            model = _load_st_model(self.model_name)
        except ImportError:
            logger.warning(
                "embedder.sentence_transformer.not_installed",
                hint="pip install sentence-transformers",
            )
            raise
        get_dim = (
            getattr(model, "get_embedding_dimension", None)
            or model.get_sentence_embedding_dimension
        )
        self._dimension = get_dim()
        self.max_tokens = int(getattr(model, "max_seq_length", None) or self.max_tokens)
        if not already:
            logger.info(
                "embedder.sentence_transformer.loaded",
                model=self.model_name,
                dim=self._dimension,
                max_tokens=self.max_tokens,
            )
        return model

    async def prepare(self) -> None:
        """Charge le modèle hors event loop."""
        import asyncio

        await asyncio.to_thread(self._load_model)

    def count_tokens(self, text: str) -> int:
        """Tokens réels, tokenizer à part."""
        model = self._model if self._model is not None else self._load_model()
        got = _counting_tokenizer(self.model_name, model)
        if got is None:
            return estimate_tokens(text)
        tok, is_rust = got
        if is_rust:
            # lecture seule : sûr entre threads
            return len(tok.encode(text or "", add_special_tokens=False).ids)
        with _COUNT_LOCK:
            return len(tok.encode(text or "", add_special_tokens=False))

    async def embed_text(self, text: str) -> list[float]:
        """Embedding brut, hors event loop."""
        import asyncio

        model = await asyncio.to_thread(self._load_model)
        embedding = await asyncio.to_thread(model.encode, text, convert_to_numpy=True)
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embeddings d'un lot."""
        import asyncio

        if not texts:
            return []
        model = await asyncio.to_thread(self._load_model)
        embeddings = await asyncio.to_thread(
            model.encode, texts, convert_to_numpy=True, batch_size=32
        )
        return embeddings.tolist()

    async def embed_query(self, text: str) -> list[float]:
        """Embedding de question, mis en cache."""
        key = self._query_prefix + (text or "")
        with self._cache_lock:
            hit = self._query_cache.get(key)
            if hit is not None:
                self._query_cache.move_to_end(key)
                return hit
        vec = await self.embed_text(key)
        with self._cache_lock:
            self._query_cache[key] = vec
            while len(self._query_cache) > self._QUERY_CACHE_SIZE:
                self._query_cache.popitem(last=False)
        return vec

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embeddings de passages (préfixés si besoin)."""
        if self._passage_prefix:
            texts = [self._passage_prefix + t for t in texts]
        return await self.embed_batch(texts)


class OpenAIEmbedder(BaseEmbedder):
    """Embeddings via l'API OpenAI (text-embedding-3-small)."""

    max_tokens = 8191

    def __init__(self, api_key: str | None = None) -> None:
        import os

        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._dimension = 1536

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        """Embedding via l'API OpenAI."""
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
        """Lot en une seule requête."""
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
    """Embeddings via Ollama (local, sans clé)."""

    # dims connues
    _KNOWN_DIMS: ClassVar[dict[str, int]] = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "bge-m3": 1024,
    }
    _KNOWN_WINDOWS: ClassVar[dict[str, int]] = {
        "nomic-embed-text": 2048,
        "mxbai-embed-large": 512,
        "all-minilm": 256,
        "bge-m3": 8192,
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
        # garde le modèle chargé
        self.keep_alive = keep_alive
        base = model.split(":")[0]
        self._dimension = dimension or self._KNOWN_DIMS.get(base, 768)
        self.max_tokens = self._KNOWN_WINDOWS.get(base, 512)

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        """Embedding via /api/embeddings."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text, "keep_alive": self.keep_alive},
                timeout=60.0,
            )
            response.raise_for_status()
            embedding = response.json()["embedding"]
        # vraie dim au 1er appel
        self._dimension = len(embedding)
        return embedding


# ── Factory ──


def get_embedder(backend: str = "ollama", **kwargs) -> BaseEmbedder:
    """Crée un embedder (ollama, sentence-transformer, openai)."""
    if backend == "ollama":
        return OllamaEmbedder(**kwargs)
    if backend == "openai":
        return OpenAIEmbedder(**kwargs)
    if backend == "sentence-transformer":
        return SentenceTransformerEmbedder(**kwargs)
    raise ValueError(f"Backend inconnu : {backend}. Options : ollama, sentence-transformer, openai")


# un embedder par réglage
_DEFAULT_EMBEDDERS: dict[tuple, BaseEmbedder] = {}
_DEFAULT_LOCK = threading.Lock()


def get_default_embedder() -> BaseEmbedder:
    """Embedder des Settings, en cache."""
    from jenny.core.config import get_settings

    settings = get_settings()
    backend = settings.embeddings_backend
    key = (backend, settings.embeddings_model, settings.llama_base_url, settings.llama_keep_alive)
    cached = _DEFAULT_EMBEDDERS.get(key)
    if cached is not None:
        return cached
    with _DEFAULT_LOCK:
        cached = _DEFAULT_EMBEDDERS.get(key)
        if cached is not None:
            return cached
        embedder: BaseEmbedder
        if backend == "sentence-transformer":
            embedder = SentenceTransformerEmbedder(model_name=settings.embeddings_model)
        elif backend == "openai":
            embedder = OpenAIEmbedder()
        else:
            embedder = OllamaEmbedder(
                model=settings.embeddings_model,
                base_url=settings.llama_base_url,
                keep_alive=settings.llama_keep_alive,
            )
        _DEFAULT_EMBEDDERS[key] = embedder
        return embedder


def reset_default_embedder() -> None:
    """Vide le cache (tests)."""
    with _DEFAULT_LOCK:
        _DEFAULT_EMBEDDERS.clear()
