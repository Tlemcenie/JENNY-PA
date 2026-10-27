"""Chat : salon vérifié, fuseau, SSE, client rattaché."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.requests import Request

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.api.routes import conversation as conv_mod
from jenny.api.routes import public_chat
from jenny.api.routes.public_chat import conversation_id_for
from jenny.core import rate_limit as core_rl
from jenny.core.config import get_settings
from jenny.core.events import event_bus
from jenny.db.session import async_session_factory
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.prestation import Prestation
from jenny.engine.factory import get_engine
from jenny.services.privacy_service import anonymize_customer

pytestmark = pytest.mark.usefixtures("db_tables")

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


@pytest.fixture(autouse=True)
def _clean():
    conv_mod.reset_salon_cache()
    public_chat.reset_limits()
    yield
    conv_mod.reset_salon_cache()
    public_chat.reset_limits()


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _salon(**kw) -> Business:
    fields = {
        "id": uuid4(),
        "name": "Salon Léa",
        "slug": f"lea-{uuid4().hex[:6]}",
        "business_hours": _OPEN_ALL,
    }
    fields.update(kw)
    async with async_session_factory() as s, s.begin():
        biz = Business(**fields)
        s.add(biz)
        for name, cents, minutes in (("Coupe femme", 3900, 45), ("Balayage", 8000, 120)):
            s.add(
                Prestation(
                    business_id=biz.id, name=name, price_cents=cents, duration_minutes=minutes
                )
            )
    return biz


def _chat(bid: UUID | str, conv: UUID | str | None = None, msg: str = "Bonjour") -> dict:
    return {"conversation_id": str(conv or uuid4()), "business_id": str(bid), "message": msg}


# ── salon inconnu ──


async def test_unknown_salon_404_before_quota_and_engine(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "env", "dev")
    monkeypatch.setattr(core_rl, "_redis", None)
    monkeypatch.setattr(core_rl, "_redis_unavailable", True)
    core_rl._local_hits.clear()
    ghost, conv = uuid4(), uuid4()
    r = await client.post("/api/v1/conversation/chat", json=_chat(ghost, conv))
    assert r.status_code == 404
    stream = await client.post("/api/v1/conversation/chat/stream", json=_chat(ghost))
    assert stream.status_code == 404
    # ni quota ni moteur
    assert not any(str(ghost) in k for k in core_rl._local_hits)
    assert await get_engine().state_manager.aget(conv) is None
    core_rl._local_hits.clear()


async def test_inactive_salon_404(client: AsyncClient) -> None:
    biz = await _salon(is_active=False)
    r = await client.post("/api/v1/conversation/chat", json=_chat(biz.id))
    assert r.status_code == 404


async def test_salon_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conv_mod, "_SALON_MAX", 5)
    async with async_session_factory() as db:
        for _ in range(12):
            assert await conv_mod._salon_open(db, uuid4()) is False
    assert len(conv_mod._salon_cache) == 5


# ── fuseau + événement ──


async def test_timezone_and_refresh_event(client: AsyncClient) -> None:
    biz = await _salon(timezone="America/Montreal")
    conv = uuid4()
    queue = event_bus.register()
    try:
        r = await client.post("/api/v1/conversation/chat", json=_chat(biz.id, conv))
        assert r.status_code == 200, r.text
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    finally:
        event_bus.unregister(queue)
    state = await get_engine().state_manager.aget(conv)
    assert state is not None and state.business_timezone == "America/Montreal"
    mine = [e for e in events if e.get("conversation_id") == str(conv)]
    assert mine, events
    # rafraîchir, pas alerter
    assert {e["kind"] for e in mine} == {"update"}


# ── widget : client rattaché ──


async def _widget(client: AsyncClient, biz: Business, visitor: str, msg: str, **kw):
    return await client.post(
        f"/api/v1/public/chat/{biz.slug}", json={"visitor_id": visitor, "message": msg}, **kw
    )


async def test_widget_booking_attaches_customer(client: AsyncClient) -> None:
    biz = await _salon()
    visitor = uuid4().hex
    conv_id = conversation_id_for(biz.id, visitor)
    r1 = await _widget(client, biz, visitor, "je réserve une coupe femme demain à 10h")
    assert r1.status_code == 200, r1.text
    async with async_session_factory() as s:
        conv = await s.get(Conversation, conv_id)
        assert conv is not None and conv.customer_id is None
    r2 = await _widget(client, biz, visitor, "C'est bon, c'est Marie Dupont")
    assert r2.status_code == 200, r2.text
    # la suite reste possible
    r3 = await _widget(client, biz, visitor, "Merci beaucoup")
    assert r3.status_code == 200, r3.text

    async with async_session_factory() as s:
        appt = (
            await s.execute(select(Appointment).where(Appointment.business_id == biz.id))
        ).scalar_one()
        conv = await s.get(Conversation, conv_id)
        msgs = (
            (await s.execute(select(Message).where(Message.conversation_id == conv_id)))
            .scalars()
            .all()
        )
    assert appt.customer_id is not None
    assert conv.customer_id == appt.customer_id
    assert len(msgs) == 6
    assert {m.customer_id for m in msgs} == {appt.customer_id}

    # droit à l'oubli : tout part
    async with async_session_factory() as s:
        await anonymize_customer(s, business_id=biz.id, customer_id=appt.customer_id)
        await s.commit()
    async with async_session_factory() as s:
        texts = (
            (
                await s.execute(
                    select(Message.content_text).where(Message.conversation_id == conv_id)
                )
            )
            .scalars()
            .all()
        )
    assert not any("Marie" in (t or "") for t in texts)


async def test_widget_ignores_dashboard_token(client: AsyncClient) -> None:
    biz = await _salon()
    other = await _salon(name="Autre")
    token = create_access_token(uuid4(), "gerant@autre.fr", [other.id])
    r = await _widget(
        client, biz, uuid4().hex, "Bonjour", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text


async def test_anon_cannot_resume_known_customer_conv(client: AsyncClient) -> None:
    biz = await _salon()
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=biz.id, full_name="Léa", phone="+33600000000")
        s.add(cust)
        await s.flush()
        conv = Conversation(business_id=biz.id, customer_id=cust.id, channel="api", status="open")
        s.add(conv)
        await s.flush()
        conv_id = conv.id
    # ce client a une autre conv
    async with async_session_factory() as s, s.begin():
        s.add(Conversation(business_id=biz.id, customer_id=cust.id, channel="whatsapp"))
    r = await client.post("/api/v1/conversation/chat", json=_chat(biz.id, conv_id))
    assert r.status_code == 403


async def test_shared_core_refuses_anonymous_customer_id() -> None:
    biz = await _salon()
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=biz.id, full_name="Léa")
        s.add(cust)
        await s.flush()
        cid = cust.id

    class _Body:
        conversation_id = uuid4()
        business_id = biz.id
        message = "Bonjour"
        channel = "widget"
        customer_id = cid
        language = None

    req = Request(
        {"type": "http", "method": "POST", "path": "/api/v1/public/chat/x", "headers": []}
    )
    async with async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await conv_mod._run_engine_chat(db, _Body(), req)
    assert getattr(exc.value, "status_code", None) == 403
