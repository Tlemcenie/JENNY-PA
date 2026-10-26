"""Webhooks : le moteur reçoit le fuseau du salon."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

import jenny.api.routes.webhooks as wh
import jenny.domain.models  # noqa: F401
from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.engine.factory import get_engine

pytestmark = pytest.mark.usefixtures("db_tables")


async def _salon(tz: str) -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", timezone=tz)
        s.add(biz)
    return biz


async def _state_tz(bid) -> str | None:
    async with async_session_factory() as s:
        conv_id = (
            await s.execute(select(Conversation.id).where(Conversation.business_id == bid))
        ).scalar_one()
    state = await get_engine().state_manager.aget(conv_id)
    return state.business_timezone if state else None


async def _sent(*args, **kwargs) -> bool:
    return True


async def test_whatsapp_passes_salon_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    biz = await _salon("America/Montreal")
    monkeypatch.setattr(wh._whatsapp, "send_reply", _sent)
    msg = {
        "from": "33611112222",
        "id": f"wamid.{uuid4().hex}",
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": "Bonjour, vous êtes ouverts demain ?"},
    }
    await wh._whatsapp_ingest_and_reply(msg, str(biz.id), {})
    assert await _state_tz(biz.id) == "America/Montreal"


async def test_instagram_passes_salon_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    biz = await _salon("Asia/Tokyo")
    monkeypatch.setattr(wh._instagram, "send_reply", _sent)
    data = {
        "sender": {"id": "ig-user-1"},
        "recipient": {"id": "ig-page-1"},
        "timestamp": 1700000000000,
        "message": {"mid": f"m.{uuid4().hex}", "text": "Bonjour"},
    }
    await wh._instagram_ingest_and_reply(data, str(biz.id))
    assert await _state_tz(biz.id) == "Asia/Tokyo"
