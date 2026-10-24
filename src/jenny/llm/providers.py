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


class MistralProvider(BaseLLMProvider):
    """provider mistral, compatible openai."""

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
    """provider llama via ollama."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str | None = None,
    ) -> None:
        self._model = model
        settings = get_settings()
        self.base_url = base_url or settings.llama_base_url
        # évite le cold-start
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

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        """vrai streaming ollama."""
        import json as _json

        import httpx

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": self._keep_alive,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = _json.loads(line)
                    except ValueError:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except Exception as e:
            logger.error("llm.llama.stream_error", error=str(e))
            # l'appelant retombe sur generate()

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


# modèle groq par défaut (seule référence)
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

    def _payload(
        self, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> dict:
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


class NanoGPTProvider(BaseLLMProvider):
    """provider nanogpt local."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/nanogpt/best_model.pt",
        tokenizer_path: str = "checkpoints/nanogpt/tokenizer.json",
    ) -> None:
        self._checkpoint_path = checkpoint_path
        self._tokenizer_path = tokenizer_path
        self._model = None
        self._tokenizer = None

    @property
    def model_name(self) -> str:
        return "nanogpt-jenny"

    @property
    def is_configured(self) -> bool:
        from pathlib import Path

        # il faut checkpoint + tokenizer
        return Path(self._checkpoint_path).exists() and Path(self._tokenizer_path).exists()

    def _load_model(self) -> None:
        if self._model is not None:
            return

        try:
            import torch
            from tokenizers import Tokenizer

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
            self._tokenizer = Tokenizer.from_file(self._tokenizer_path)
            logger.info(
                "llm.nanogpt.loaded",
                path=self._checkpoint_path,
                step=checkpoint.get("step"),
                val_loss=checkpoint.get("best_val_loss"),
            )
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

        if self._model is None or self._tokenizer is None:
            return LLMResponse(
                content="[NanoGPT non disponible — entraîne le modèle d'abord]",
                model=self.model_name,
                finish_reason="error",
            )

        try:
            import torch

            from nanogpt.generate import generate as nano_generate

            # prompt tronqué au contexte
            block = self._model.config.block_size
            prompt_ids = self._tokenizer.encode(prompt).ids[-(block - 1) :]
            idx = torch.tensor([prompt_ids or [0]], dtype=torch.long)
            out = nano_generate(
                self._model,
                idx,
                max_new_tokens=max(1, min(max_tokens, 200)),
                temperature=max(temperature, 1e-3),
                top_k=40,
            )
            gen_ids = out[0].tolist()[len(prompt_ids) :]
            text = self._tokenizer.decode(gen_ids).strip()
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


# factory


def get_llm_provider(provider_name: str | None = None, **kwargs) -> BaseLLMProvider:
    """fabrique le provider demandé."""
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
                async for token in p.generate_stream(prompt, system_prompt, temperature, max_tokens):
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
    """provider actif avec repli groq."""
    from jenny.llm.runtime import active_provider_model

    name, model = active_provider_model()
    # nanogpt ne prend pas model=
    kwargs = {"model": model} if (model and name != "nanogpt") else {}
    try:
        primary = get_llm_provider(name, **kwargs)
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
