"""Compte les requêtes SQL des routes chaudes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.user import User

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@contextmanager
def count_sql():
    """Collecte les requêtes émises."""
    stmts: list[str] = []

    def _on(conn, cursor, statement, params, context, executemany):
        stmts.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield stmts
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncClient:
    from jenny.engine.factory import reset_engine

    reset_engine()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


async def _auth(client: AsyncClient, email: str) -> tuple[dict, UUID]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Salon", "email": email, "password": _PASSWORD},
    )
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, UUID(bid)


async def _seed_inbox(bid: UUID, n_conv: int = 6, n_msg: int = 12) -> list[UUID]:
    """Clients + conversations + messages + RDV."""
    now = datetime.now(UTC)
    conv_ids: list[UUID] = []
    async with async_session_factory() as s, s.begin():
        for i in range(n_conv):
            cust = Customer(business_id=bid, full_name=f"Client {i}")
            s.add(cust)
            await s.flush()
            conv = Conversation(
                business_id=bid,
                customer_id=cust.id,
                channel="whatsapp",
                status="open",
                message_count=n_msg,
                last_message_at=now - timedelta(minutes=i),
            )
            s.add(conv)
            await s.flush()
            conv_ids.append(conv.id)
            for j in range(n_msg):
                # dernier message = entrant si i pair
                last = j == n_msg - 1
                direction = ("inbound" if i % 2 == 0 else "outbound") if last else (
                    "inbound" if j % 2 == 0 else "outbound"
                )
                s.add(
                    Message(
                        conversation_id=conv.id,
                        business_id=bid,
                        customer_id=cust.id,
                        external_message_id=str(uuid4()),
                        channel="whatsapp",
                        direction=direction,
                        content_text=f"conv {i} msg {j}",
                        created_at=now - timedelta(minutes=i, seconds=n_msg - j),
                        received_at=now - timedelta(minutes=i, seconds=n_msg - j),
                    )
                )
            for h in (-72, -48, 24):
                start = now + timedelta(hours=h + i)
                s.add(
                    Appointment(
                        business_id=bid,
                        customer_id=cust.id,
                        conversation_id=conv.id,
                        title="Coupe",
                        start_at=start,
                        end_at=start + timedelta(minutes=30),
                        status="confirmed" if h < 0 else "scheduled",
                    )
                )
        s.add(Prestation(business_id=bid, name="Coupe", price_cents=4000, duration_minutes=30))
    return conv_ids


@pytest.mark.asyncio
async def test_inbox_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "inbox@perf.com")
    await _seed_inbox(bid)

    with count_sql() as stmts:
        r = await client.get("/api/v1/conversations", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    print(f"\n[perf] inbox: {len(stmts)} requêtes")

    # contenu inchangé
    assert data["total"] == 6 and len(data["conversations"]) == 6
    first = data["conversations"][0]
    assert first["customer_name"] == "Client 0"
    assert first["last_message_preview"] == "conv 0 msg 11"
    assert first["awaiting_reply"] is True
    assert data["conversations"][1]["awaiting_reply"] is False
    # aucune requête ne lit tout l'historique
    assert not any("customer_documents" in s for s in stmts)
    assert len(stmts) <= 3, stmts


@pytest.mark.asyncio
async def test_inbox_total_with_pages(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "pages@perf.com")
    await _seed_inbox(bid, n_conv=5, n_msg=2)

    p1 = (await client.get("/api/v1/conversations?limit=2", headers=headers)).json()
    p3 = (await client.get("/api/v1/conversations?limit=2&offset=4", headers=headers)).json()
    past = (await client.get("/api/v1/conversations?limit=2&offset=10", headers=headers)).json()
    assert p1["total"] == 5 and len(p1["conversations"]) == 2
    assert p3["total"] == 5 and len(p3["conversations"]) == 1
    assert past["total"] == 5 and past["conversations"] == []


@pytest.mark.asyncio
async def test_salon_stats_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "stats@perf.com")
    await _seed_inbox(bid)

    with count_sql() as stmts:
        r = await client.get("/api/v1/salon/stats", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    print(f"\n[perf] salon/stats: {len(stmts)} requêtes")

    assert d["completed"] == 12 and d["upcoming"] == 6
    assert d["clients_total"] == 6 and d["loyal_clients"] == 6
    assert d["revenue_upcoming_eur"] == 240.0
    assert d["top_prestations"] == [{"name": "Coupe", "count": 12}]
    assert not any("FROM messages" in s for s in stmts)
    assert len(stmts) <= 8, stmts


@pytest.mark.asyncio
async def test_customer_context_no_cascade(client: AsyncClient, db_tables: None) -> None:
    from jenny.services.learning_service import load_customer_context

    _headers, bid = await _auth(client, "ctx@perf.com")
    await _seed_inbox(bid, n_conv=2, n_msg=20)
    async with async_session_factory() as s:
        cid = (await s.execute(select(Customer.id).where(Customer.full_name == "Client 1"))).scalar()

    async with async_session_factory() as s:
        with count_sql() as stmts:
            ctx = await load_customer_context(s, bid, cid)
    print(f"\n[perf] contexte client: {len(stmts)} requêtes")
    assert any("Client" in line and "s'appelle" in line for line in ctx)
    assert any("« Coupe »" in line for line in ctx)
    assert not any("FROM messages" in s or "FROM conversations" in s for s in stmts)
    assert len(stmts) == 3, stmts

    # client d'un autre salon : rien
    async with async_session_factory() as s:
        other = await load_customer_context(s, uuid4(), cid)
    assert not any("s'appelle" in line for line in other)


@pytest.mark.asyncio
async def test_admin_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, _bid = await _auth(client, "boss@perf.com")
    async with async_session_factory() as s, s.begin():
        await s.execute(update(User).where(User.email == "boss@perf.com").values(is_superuser=True))
        for i in range(5):
            b = Business(name=f"Salon {i}", slug=f"salon-perf-{i}")
            s.add(b)
            await s.flush()
            for _ in range(i):
                s.add(Conversation(business_id=b.id, channel="whatsapp", status="open"))
            u = User(email=f"u{i}@perf.com", full_name=f"U {i}")
            s.add(u)
            await s.flush()
            s.add(BusinessMember(user_id=u.id, business_id=b.id, role="owner"))

    with count_sql() as stmts:
        r = await client.get("/api/v1/admin/businesses", headers=headers)
    assert r.status_code == 200, r.text
    print(f"\n[perf] admin/businesses: {len(stmts)} requêtes")
    by_slug = {b["slug"]: b for b in r.json()}
    assert by_slug["salon-perf-3"]["conversations"] == 3
    assert by_slug["salon-perf-3"]["members"] == 1
    assert by_slug["salon-perf-0"]["conversations"] == 0
    assert len(stmts) <= 5, stmts

    with count_sql() as stmts:
        r = await client.get("/api/v1/admin/users", headers=headers)
    assert r.status_code == 200, r.text
    print(f"\n[perf] admin/users: {len(stmts)} requêtes")
    by_mail = {u["email"]: u for u in r.json()}
    assert by_mail["u2@perf.com"]["businesses"] == 1
    assert by_mail["boss@perf.com"]["businesses"] == 1
    assert len(stmts) <= 5, stmts

    with count_sql() as stmts:
        r = await client.get("/api/v1/admin/overview", headers=headers)
    assert r.status_code == 200, r.text
    print(f"\n[perf] admin/overview: {len(stmts)} requêtes")
    assert r.json()["businesses"] == 6 and r.json()["users"] == 6
    assert len(stmts) <= 4, stmts
