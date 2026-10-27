"""abstraction des providers llm."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """réponse standard d'un llm."""

    content: str
    model: str
    usage: dict | None = None
    finish_reason: str = "stop"


class BaseLLMProvider(ABC):
    """interface commune des providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """nom du modèle."""
        ...

    @property
    def is_configured(self) -> bool:
        """credentials présents ?"""
        return True

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """génère une réponse."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """embedding d'un texte."""
        ...

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        """faux streaming par défaut."""
        resp = await self.generate(prompt, system_prompt, temperature, max_tokens)
        if resp.finish_reason != "error" and resp.content:
            yield resp.content


class OpenAIProvider(BaseLLMProvider):
    """provider openai."""

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


GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
# modèles à raisonnement (budget séparé)
_REASONING_MODELS = ("gpt-oss", "qwen3", "deepseek-r1")
# balises de pensée parfois laissées
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S | re.I)


class GroqProvider(BaseLLMProvider):
    """provider groq, compatible openai."""

    def __init__(
        self,
        model: str = GROQ_DEFAULT_MODEL,
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

    def _payload(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> dict:
        """Corps de requête, adapté au modèle."""
        body: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # raisonnement bref, sinon réponse vide
        if any(tag in self._model.lower() for tag in _REASONING_MODELS):
            body["reasoning_effort"] = "low"
            body["max_tokens"] = max(max_tokens, 400)
        return body

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
                    json=self._payload(messages, temperature, max_tokens),
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                content = _THINK_RE.sub("", msg.get("content") or "").strip()
                usage = data.get("usage")
                # vide = budget parti en raisonnement
                if not content:
                    logger.error(
                        "llm.groq.empty_content",
                        model=self._model,
                        finish=data["choices"][0].get("finish_reason"),
                    )
                    return LLMResponse(
                        content="", model=self._model, finish_reason="error", usage=usage
                    )
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


def get_llm_provider(provider_name: str | None = None, **kwargs) -> BaseLLMProvider:
    """fabrique le provider demandé."""
    settings = get_settings()
    name = (provider_name or settings.llm_provider or "groq").lower()

    if "model" not in kwargs and name == settings.llm_provider and settings.llm_model:
        kwargs["model"] = settings.llm_model

    providers: dict[str, type[BaseLLMProvider]] = {
        "openai": OpenAIProvider,
        "groq": GroqProvider,
    }

    provider_class = providers.get(name)
    if provider_class is None:
        raise ValueError(f"Provider inconnu : {name}. Options : {list(providers.keys())}")

    return provider_class(**kwargs)


class FallbackLLMProvider(BaseLLMProvider):
    """essaie les providers dans l'ordre."""

    def __init__(self, providers: list[BaseLLMProvider]) -> None:
        self._providers = [p for p in providers if p is not None]

    @property
    def model_name(self) -> str:
        return self._providers[0].model_name if self._providers else "none"

    @property
    def is_configured(self) -> bool:
        return any(p.is_configured for p in self._providers)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        last: LLMResponse | None = None
        for p in self._providers:
            if not p.is_configured:
                continue
            try:
                resp = await p.generate(prompt, system_prompt, temperature, max_tokens)
            except Exception as e:  # on passe au suivant
                logger.warning("llm.fallback.error", provider=p.model_name, error=str(e))
                continue
            if resp.finish_reason != "error" and (resp.content or "").strip():
                return resp
            last = resp
        return last or LLMResponse(content="", model="none", finish_reason="error")

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        for p in self._providers:
            if not p.is_configured:
                continue
            try:
                yielded = False
                async for token in p.generate_stream(
                    prompt, system_prompt, temperature, max_tokens
                ):
                    yielded = True
                    yield token
                if yielded:
                    return
            except Exception as e:
                logger.warning("llm.fallback.stream_error", provider=p.model_name, error=str(e))
                continue
        # l'appelant retombera sur generate()

    async def embed(self, text: str) -> list[float]:
        for p in self._providers:
            if p.is_configured:
                return await p.embed(text)
        return []


def get_default_llm_provider() -> BaseLLMProvider | None:
    """provider des réglages, repli groq."""
    name = (get_settings().llm_provider or "groq").lower()
    try:
        primary = get_llm_provider(name)
    except ValueError:
        logger.warning("llm.unknown_provider", provider=name)
        primary = None

    # repli groq
    groq: BaseLLMProvider | None = None
    if name != "groq":
        try:
            g = get_llm_provider("groq", model=GROQ_DEFAULT_MODEL)
            groq = g if g.is_configured else None
        except Exception:
            groq = None

    chain: list[BaseLLMProvider] = []
    if primary is not None and primary.is_configured:
        chain.append(primary)
    if groq is not None:
        chain.append(groq)

    if not chain:
        logger.info("llm.provider.none_available", provider=name)
        return None
    if len(chain) == 1:
        logger.info("llm.provider.ready", provider=chain[0].model_name)
        return chain[0]
    logger.info("llm.provider.ready_with_fallback", primary=chain[0].model_name, fallback="groq")
    return FallbackLLMProvider(chain)
