"""Abstraction des fournisseurs LLM.

Fournit une interface unifiée pour appeler différents LLM
(OpenAI, Groq, Mistral, Llama, NanoGPT local) sans coupler le reste
de l'application à un provider spécifique.

Toutes les clés d'API sont consommées via `get_settings()` (préfixe
`JENNY_*`). Aucun `os.getenv()` direct ici afin de garantir la
cohérence avec `.env.example` et `.env`.

Providers supportés :
- OpenAI (GPT-4o, GPT-4o-mini)
- Groq (Llama 3.3 70B, Mixtral, etc.)
- Mistral (Mistral Large, Mistral Small)
- Llama (via Ollama ou vLLM local)
- NanoGPT (modèle maison entraîné from scratch)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """Réponse standardisée d'un LLM."""

    content: str
    model: str
    usage: dict | None = None
    finish_reason: str = "stop"


class BaseLLMProvider(ABC):
    """Interface abstraite pour les providers LLM."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nom du modèle utilisé."""
        ...

    @property
    def is_configured(self) -> bool:
        """Indique si le provider possède les credentials nécessaires."""
        return True

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Génère une réponse à partir d'un prompt."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Génère un vecteur d'embedding pour un texte."""
        ...


class OpenAIProvider(BaseLLMProvider):
    """Provider OpenAI (GPT-4o, GPT-4o-mini)."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self.api_key = api_key if api_key is not None else get_settings().openai_api_key
        self.base_url = "https://api.openai.com/v1"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            logger.error("llm.openai.no_api_key")
            return LLMResponse(
                content="[Clé API OpenAI manquante]",
                model=self._model,
                finish_reason="error",
            )

        logger.info("llm.openai.generate", model=self._model)
        try:
            import httpx

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage")
                return LLMResponse(content=content, model=self._model, usage=usage)
        except Exception as e:
            logger.error("llm.openai.error", error=str(e))
            return LLMResponse(
                content="[Erreur OpenAI]",
                model=self._model,
                finish_reason="error",
            )

    async def embed(self, text: str) -> list[float]:
        if not self.api_key:
            logger.warning("llm.openai.embed_no_api_key")
            return [0.0] * 1536

        logger.info("llm.openai.embed", text_length=len(text))
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "text-embedding-3-small",
                        "input": text,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return list(data["data"][0]["embedding"])
        except Exception as e:
            logger.error("llm.openai.embed_error", error=str(e))
            return [0.0] * 1536


class MistralProvider(BaseLLMProvider):
    """Provider Mistral AI (compatible OpenAI)."""

    def __init__(
        self,
        model: str = "mistral-small-latest",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self.api_key = api_key if api_key is not None else get_settings().mistral_api_key
        self.base_url = base_url or "https://api.mistral.ai/v1"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            logger.error("llm.mistral.no_api_key")
            return LLMResponse(
                content="[Clé API Mistral manquante]",
                model=self._model,
                finish_reason="error",
            )

        logger.info("llm.mistral.generate", model=self._model)
        try:
            import httpx

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage")
                return LLMResponse(content=content, model=self._model, usage=usage)
        except Exception as e:
            logger.error("llm.mistral.error", error=str(e))
            return LLMResponse(
                content="[Erreur Mistral]",
                model=self._model,
                finish_reason="error",
            )

    async def embed(self, text: str) -> list[float]:
        logger.info("llm.mistral.embed", text_length=len(text))
        return [0.0] * 1024


class LlamaProvider(BaseLLMProvider):
    """Provider Llama via Ollama (ou autre runtime local exposant `/api/chat`)."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str | None = None,
    ) -> None:
        self._model = model
        settings = get_settings()
        self.base_url = base_url or settings.llama_base_url
        # Garde le modèle chargé entre les requêtes (évite le cold-start).
        self._keep_alive = settings.llama_keep_alive

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        logger.info("llm.llama.generate", model=self._model)
        try:
            import httpx

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "keep_alive": self._keep_alive,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        },
                    },
                    timeout=120.0,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("message", {}).get("content", "")
                return LLMResponse(content=content, model=self._model)
        except Exception as e:
            logger.error("llm.llama.error", error=str(e))
            return LLMResponse(
                content="[Erreur Llama/Ollama]",
                model=self._model,
                finish_reason="error",
            )

    async def embed(self, text: str) -> list[float]:
        logger.info("llm.llama.embed", text_length=len(text))
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={
                        "model": self._model,
                        "prompt": text,
                        "keep_alive": self._keep_alive,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                return list(data.get("embedding", [0.0] * 384))
        except Exception:
            return [0.0] * 384


class GroqProvider(BaseLLMProvider):
    """Provider Groq (Llama 3.3 70B, Mixtral...). API compatible OpenAI."""

    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self.api_key = api_key if api_key is not None else get_settings().groq_api_key
        self.base_url = "https://api.groq.com/openai/v1"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            logger.error("llm.groq.no_api_key")
            return LLMResponse(
                content="[Clé API Groq manquante]",
                model=self._model,
                finish_reason="error",
            )

        logger.info("llm.groq.generate", model=self._model)
        try:
            import httpx

            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage")
                return LLMResponse(content=content, model=self._model, usage=usage)
        except Exception as e:
            logger.error("llm.groq.error", error=str(e))
            return LLMResponse(
                content="[Erreur Groq]",
                model=self._model,
                finish_reason="error",
            )

    async def embed(self, text: str) -> list[float]:
        logger.warning("llm.groq.embed_unsupported")
        return [0.0] * 384


class NanoGPTProvider(BaseLLMProvider):
    """Provider pour le modèle NanoGPT local (PyTorch, entraîné from scratch)."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/nanogpt/best_model.pt",
    ) -> None:
        self._checkpoint_path = checkpoint_path
        self._model = None
        self._tokenizer = None

    @property
    def model_name(self) -> str:
        return "nanogpt-jenny"

    @property
    def is_configured(self) -> bool:
        from pathlib import Path

        return Path(self._checkpoint_path).exists()

    def _load_model(self) -> None:
        if self._model is not None:
            return

        try:
            import torch

            from nanogpt.config import NanoGPTConfig
            from nanogpt.model import NanoGPT

            checkpoint = torch.load(
                self._checkpoint_path,
                map_location="cpu",
                weights_only=False,
            )
            config = checkpoint.get("config", NanoGPTConfig())
            self._model = NanoGPT(config)
            self._model.load_state_dict(checkpoint["model_state_dict"])
            self._model.eval()
            logger.info("llm.nanogpt.loaded", path=self._checkpoint_path)
        except (FileNotFoundError, ImportError) as e:
            logger.warning("llm.nanogpt.not_available", error=str(e))

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> LLMResponse:
        logger.info("llm.nanogpt.generate")
        self._load_model()

        if self._model is None:
            return LLMResponse(
                content="[NanoGPT non disponible]",
                model=self.model_name,
                finish_reason="error",
            )

        try:
            from nanogpt.generate import generate_text

            text = generate_text(
                model=self._model,
                prompt=prompt,
                max_new_tokens=max_tokens,
                temperature=temperature,
            )
            return LLMResponse(content=text, model=self.model_name)
        except Exception as e:
            logger.error("llm.nanogpt.error", error=str(e))
            return LLMResponse(
                content="[Erreur NanoGPT]",
                model=self.model_name,
                finish_reason="error",
            )

    async def embed(self, text: str) -> list[float]:
        logger.warning("llm.nanogpt.embed_unsupported")
        return [0.0] * 256


# ── Factory ──


def get_llm_provider(provider_name: str | None = None, **kwargs) -> BaseLLMProvider:
    """Factory pour créer un provider LLM.

    Args:
        provider_name: "openai" | "groq" | "mistral" | "llama" | "nanogpt".
            Par défaut, utilise `settings.llm_provider`.
        **kwargs: passés au constructeur du provider (p.ex. `model=`).

    Returns:
        Instance du provider correspondant.
    """
    settings = get_settings()
    name = (provider_name or settings.llm_provider or "groq").lower()

    if "model" not in kwargs and name == settings.llm_provider and settings.llm_model:
        kwargs["model"] = settings.llm_model

    providers: dict[str, type[BaseLLMProvider]] = {
        "openai": OpenAIProvider,
        "groq": GroqProvider,
        "mistral": MistralProvider,
        "llama": LlamaProvider,
        "nanogpt": NanoGPTProvider,
    }

    provider_class = providers.get(name)
    if provider_class is None:
        raise ValueError(
            f"Provider inconnu : {name}. Options : {list(providers.keys())}"
        )

    return provider_class(**kwargs)


def get_default_llm_provider() -> BaseLLMProvider | None:
    """Construit le provider LLM par défaut depuis Settings.

    Renvoie None si aucun provider n'est configuré (pas de clé/endpoint).
    Le code appelant doit alors basculer sur un fallback (templates).
    """
    settings = get_settings()
    try:
        provider = get_llm_provider(settings.llm_provider)
    except ValueError:
        logger.warning("llm.unknown_provider", provider=settings.llm_provider)
        return None

    if not provider.is_configured:
        logger.info(
            "llm.provider.not_configured",
            provider=settings.llm_provider,
            hint="renseignez JENNY_<PROVIDER>_API_KEY pour activer le LLM",
        )
        return None

    logger.info(
        "llm.provider.ready",
        provider=settings.llm_provider,
        model=provider.model_name,
    )
    return provider
