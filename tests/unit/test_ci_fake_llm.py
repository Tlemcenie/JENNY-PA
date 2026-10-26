"""Chemin LLM testé sans réseau, via un faux provider."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business

pytestmark = pytest.mark.usefixtures("db_tables")

_DISCLOSURE = "assistante virtuelle"


async def _chat(client, conv: str, biz: str, message: str) -> dict:
    """Un tour de chat."""
    # salon réel, sinon 404
    async with async_session_factory() as s, s.begin():
        if await s.get(Business, UUID(biz)) is None:
            s.add(Business(id=UUID(biz), name="Salon", slug=f"s-{uuid4().hex[:8]}"))
    r = await client.post(
        "/api/v1/conversation/chat",
        json={"conversation_id": conv, "business_id": biz, "message": message},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_chat_goes_through_llm(fake_llm, async_client) -> None:
    """La réponse vient du LLM."""
    fake_llm.replies = ["Oui, on fait des balayages, c'est notre spécialité."]
    data = await _chat(async_client, str(uuid4()), str(uuid4()), "Vous faites des balayages ?")
    assert len(fake_llm.calls) == 1
    assert "balayages, c'est notre spécialité" in data["response"]
    # le prompt porte le message client
    assert "balayages" in fake_llm.calls[0]["prompt"]
    assert fake_llm.calls[0]["system_prompt"]


async def test_first_reply_discloses_ai(fake_llm, async_client) -> None:
    """AI Act : divulgation au 1er tour."""
    fake_llm.replies = ["Bonjour ! Que puis-je faire pour vous ?", "Avec plaisir."]
    conv, biz = str(uuid4()), str(uuid4())
    first = await _chat(async_client, conv, biz, "Bonjour")
    second = await _chat(async_client, conv, biz, "Je cherche une info")
    assert _DISCLOSURE in first["response"]
    # pas répété ensuite
    assert _DISCLOSURE not in second["response"]
    assert len(fake_llm.calls) == 2


async def test_llm_error_falls_back_to_template(fake_llm, async_client) -> None:
    """LLM en panne : template, pas de charabia."""
    from jenny.llm.providers import LLMResponse

    async def _boom(*args, **kwargs) -> LLMResponse:
        return LLMResponse(content="[Erreur Groq]", model="fake-llm", finish_reason="error")

    fake_llm.generate = _boom  # type: ignore[method-assign]
    data = await _chat(async_client, str(uuid4()), str(uuid4()), "Bonjour !")
    assert "[Erreur" not in data["response"]
    assert data["response"].strip()


async def test_without_fake_llm_uses_templates(async_client) -> None:
    """Sans faux LLM : chemin templates."""
    from jenny.engine.factory import get_engine

    data = await _chat(async_client, str(uuid4()), str(uuid4()), "Bonjour !")
    assert data["intent"] == "greeting"
    assert get_engine().response_generator is None
