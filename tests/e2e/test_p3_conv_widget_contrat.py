"""Contrat chat / widget : client lu en base."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.api.routes import conversation as conv_mod
from jenny.api.routes import public_chat
from jenny.api.routes.public_chat import conversation_id_for
from jenny.db.session import async_session_factory
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.prestation import Prestation
from jenny.engine.factory import get_engine

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


async def _salon() -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon Léa", slug=f"lea-{uuid4().hex[:6]}", business_hours=_OPEN_ALL
        )
        s.add(biz)
        for name, cents, minutes in (("Coupe femme", 3900, 45), ("Balayage", 8000, 120)):
            s.add(
                Prestation(
                    business_id=biz.id, name=name, price_cents=cents, duration_minutes=minutes
                )
            )
    return biz


async def _say(client: AsyncClient, biz: Business, visitor: str, msg: str):
    return await client.post(
        f"/api/v1/public/chat/{biz.slug}", json={"visitor_id": visitor, "message": msg}
    )


async def _named_visit(client: AsyncClient, biz: Business, visitor: str) -> Conversation:
    """Réserve et donne son nom."""
    r = await _say(client, biz, visitor, "je réserve une coupe femme demain à 10h")
    assert r.status_code == 200, r.text
    r = await _say(client, biz, visitor, "C'est bon, c'est Marie Dupont")
    assert r.status_code == 200, r.text
    async with async_session_factory() as s:
        conv = await s.get(Conversation, conversation_id_for(biz.id, visitor))
    assert conv is not None and conv.customer_id is not None
    return conv


def _widget_req() -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/api/v1/public/chat/x", "headers": []}
    )


class _Body:
    def __init__(self, conv_id, business_id, channel="widget") -> None:
        self.conversation_id = conv_id
        self.business_id = business_id
        self.message = "Bonjour"
        self.channel = channel
        self.customer_id = None
        self.language = None


# ── reprise après perte de l'état ──


async def test_return_after_state_loss_no_duplicate(client: AsyncClient) -> None:
    biz = await _salon()
    visitor = uuid4().hex
    conv = await _named_visit(client, biz, visitor)
    first = conv.customer_id

    # redémarrage : état perdu
    await get_engine().state_manager.adelete(conv.id)

    r = await _say(client, biz, visitor, "je réserve un balayage après-demain à 14h")
    assert r.status_code == 200, r.text
    r = await _say(client, biz, visitor, "Merci beaucoup")
    assert r.status_code == 200, r.text

    # moteur réaligné sur la base
    state = await get_engine().state_manager.aget(conv.id)
    assert state is not None and state.customer_id == first
    async with async_session_factory() as s:
        n_cust = await s.scalar(
            select(func.count()).select_from(Customer).where(Customer.business_id == biz.id)
        )
        appts = (
            (await s.execute(select(Appointment).where(Appointment.business_id == biz.id)))
            .scalars()
            .all()
        )
        owners = set(
            (await s.execute(select(Message.customer_id).where(Message.conversation_id == conv.id)))
            .scalars()
            .all()
        )
        again = await s.get(Conversation, conv.id)
    # pas de doublon
    assert n_cust == 1
    assert len(appts) == 2
    assert {a.customer_id for a in appts} == {first}
    assert again.customer_id == first
    assert owners == {first}


async def test_lost_attach_turn_recovered(client: AsyncClient) -> None:
    """Tour du nom non rattaché."""
    biz = await _salon()
    visitor = uuid4().hex
    conv_id = conversation_id_for(biz.id, visitor)
    assert (await _say(client, biz, visitor, "Bonjour")).status_code == 200
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=biz.id, full_name="Marie Dupont")
        s.add(cust)
        await s.flush()
        cid = cust.id
    # l'état a le client, la base non
    state = await get_engine().state_manager.aget(conv_id)
    state.customer_id = cid
    await get_engine().state_manager.asave(state)

    r = await _say(client, biz, visitor, "Merci !")
    assert r.status_code == 200, r.text
    async with async_session_factory() as s:
        conv = await s.get(Conversation, conv_id)
        owners = set(
            (await s.execute(select(Message.customer_id).where(Message.conversation_id == conv_id)))
            .scalars()
            .all()
        )
    assert conv.customer_id == cid
    assert owners == {cid}


# ── personne ne reprend la conv d'un autre ──


async def test_anon_chat_cannot_take_widget_conv(client: AsyncClient) -> None:
    biz = await _salon()
    visitor = uuid4().hex
    conv = await _named_visit(client, biz, visitor)
    # id fuité, autre route
    body = {"conversation_id": str(conv.id), "business_id": str(biz.id), "message": "Mon rdv ?"}
    r = await client.post("/api/v1/conversation/chat", json=body)
    assert r.status_code == 403
    r = await client.post("/api/v1/conversation/chat", json={**body, "channel": "widget"})
    assert r.status_code == 403
    assert "Marie" not in r.text


async def test_widget_cannot_take_chat_conv() -> None:
    biz = await _salon()
    async with async_session_factory() as s, s.begin():
        conv = Conversation(business_id=biz.id, channel="api", status="open", message_count=0)
        s.add(conv)
        await s.flush()
        conv_id = conv.id
    async with async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await conv_mod._run_engine_chat(db, _Body(conv_id, biz.id), _widget_req())
    assert exc.value.status_code == 403


async def test_state_with_old_customer_refused(client: AsyncClient) -> None:
    biz = await _salon()
    visitor = uuid4().hex
    conv_id = conversation_id_for(biz.id, visitor)
    assert (await _say(client, biz, visitor, "Bonjour")).status_code == 200
    async with async_session_factory() as s, s.begin():
        old = Customer(
            business_id=biz.id,
            full_name="Paul Martin",
            phone="+33600000009",
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        s.add(old)
        await s.flush()
        old_id = old.id
    state = await get_engine().state_manager.aget(conv_id)
    state.customer_id = old_id
    await get_engine().state_manager.asave(state)

    r = await _say(client, biz, visitor, "Mon prochain rdv ?")
    assert r.status_code == 403
    assert "Paul" not in r.text


async def test_customer_seen_elsewhere_refused(client: AsyncClient) -> None:
    """Client vu sur WhatsApp : stop."""
    biz = await _salon()
    visitor = uuid4().hex
    conv = await _named_visit(client, biz, visitor)
    async with async_session_factory() as s, s.begin():
        s.add(Conversation(business_id=biz.id, customer_id=conv.customer_id, channel="whatsapp"))
    r = await _say(client, biz, visitor, "Je décale mon rdv")
    assert r.status_code == 403


async def test_other_visitor_gets_own_conv(client: AsyncClient) -> None:
    biz = await _salon()
    alice, bob = uuid4().hex, uuid4().hex
    conv = await _named_visit(client, biz, alice)
    assert (await _say(client, biz, bob, "Bonjour")).status_code == 200
    bob_id = conversation_id_for(biz.id, bob)
    assert bob_id != conv.id
    async with async_session_factory() as s:
        other = await s.get(Conversation, bob_id)
        bob_owner = set(
            (await s.execute(select(Message.customer_id).where(Message.conversation_id == bob_id)))
            .scalars()
            .all()
        )
    assert other.customer_id is None
    assert bob_owner == {None}
    state = await get_engine().state_manager.aget(bob_id)
    assert state is not None and state.customer_id is None


async def test_widget_never_sends_customer_id(client: AsyncClient) -> None:
    biz = await _salon()
    r = await client.post(
        f"/api/v1/public/chat/{biz.slug}",
        json={"visitor_id": uuid4().hex, "message": "Bonjour", "customer_id": str(uuid4())},
    )
    assert r.status_code == 422
