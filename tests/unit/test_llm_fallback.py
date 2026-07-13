"""Chaîne de repli LLM : ne jamais servir de charabia si le modèle actif échoue."""

import pytest

from jenny.llm.providers import BaseLLMProvider, FallbackLLMProvider, LLMResponse


class _Raises(BaseLLMProvider):
    model_name = "raises"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, *a, **k) -> LLMResponse:
        raise RuntimeError("injoignable")

    async def embed(self, text: str):
        return []


class _Errors(BaseLLMProvider):
    """Renvoie un finish_reason=error (ex. provider joignable mais en panne)."""

    model_name = "errors"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, *a, **k) -> LLMResponse:
        return LLMResponse(content="", model="errors", finish_reason="error")

    async def embed(self, text: str):
        return []


class _Good(BaseLLMProvider):
    model_name = "good"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, *a, **k) -> LLMResponse:
        return LLMResponse(content="Oui, on fait des balayages !", model="good")

    async def embed(self, text: str):
        return []


@pytest.mark.asyncio
async def test_fallback_on_exception() -> None:
    chain = FallbackLLMProvider([_Raises(), _Good()])
    r = await chain.generate("x")
    assert r.content == "Oui, on fait des balayages !"
    assert r.finish_reason != "error"


@pytest.mark.asyncio
async def test_fallback_on_error_finish_reason() -> None:
    chain = FallbackLLMProvider([_Errors(), _Good()])
    r = await chain.generate("x")
    assert r.content == "Oui, on fait des balayages !"


@pytest.mark.asyncio
async def test_no_fallback_when_primary_ok() -> None:
    # Le principal répond bien → on ne bascule pas (même « moche » = valide).
    chain = FallbackLLMProvider([_Good(), _Errors()])
    r = await chain.generate("x")
    assert r.model == "good"


@pytest.mark.asyncio
async def test_all_fail_returns_error() -> None:
    chain = FallbackLLMProvider([_Raises(), _Errors()])
    r = await chain.generate("x")
    assert r.finish_reason == "error"
