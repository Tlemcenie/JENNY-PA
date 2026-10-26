"""Requêtes SQL des chemins chauds (passe 2)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, update

import jenny.domain.models  # noqa: F401
from jenny.api.dependencies import CurrentPrincipal, get_superuser
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.repositories.conversation_repo import ConversationRepository
from jenny.db.repositories.customer_repo import CustomerRepository
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.order import Order
from jenny.domain.models.support_ticket import SupportTicket
from jenny.domain.models.user import User
from jenny.domain.schemas.message import MessageIn
from jenny.services.ingestion_service import MessageIngestionService

_PASSWORD = "Strong#1234"
PHONE = "+33611223344"
HANDLE = "lea.coiffure"


@contextmanager
def count_sql():
    """Requêtes émises."""
    stmts: list[str] = []

    def _on(conn, cursor, statement, params, context, executemany):
        stmts.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield stmts
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


def _report(label: str, stmts: list[str]) -> None:
    print(f"\n[perf p2] {label}: {len(stmts)} requêtes")


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


async def _seed_customer(bid: UUID, n_conv: int = 3, n_msg: int = 8) -> UUID:
    """Une cliente avec un vrai historique."""
    now = datetime.now(UTC)
    async with async_session_factory() as s, s.begin():
        cust = Customer(
            business_id=bid,
            full_name="Léa Martin",
            email="lea@client.fr",
            phone=PHONE,
            instagram_handle=HANDLE,
            tags=["fidèle"],
        )
        s.add(cust)
        await s.flush()
        for i in range(n_conv):
            conv = Conversation(
                business_id=bid,
                customer_id=cust.id,
                channel="whatsapp" if i == 0 else "instagram",
                external_conversation_id=f"ext-{i}",
                status="open",
                message_count=n_msg,
                last_message_at=now - timedelta(hours=i),
                last_message_preview=f"aperçu {i}",
                tags=["balayage"] if i == 0 else None,
            )
            s.add(conv)
            await s.flush()
            for j in range(n_msg):
                s.add(
                    Message(
                        conversation_id=conv.id,
                        business_id=bid,
                        customer_id=cust.id,
                        external_message_id=str(uuid4()),
                        channel=conv.channel,
                        direction="inbound" if j % 2 == 0 else "outbound",
                        content_text=f"balayage message {i}-{j}",
                        received_at=now - timedelta(hours=i, minutes=n_msg - j),
                    )
                )
            start = now + timedelta(days=i + 1)
            s.add(
                Appointment(
                    business_id=bid,
                    customer_id=cust.id,
                    conversation_id=conv.id,
                    title="Balayage",
                    start_at=start,
                    end_at=start + timedelta(hours=1),
                    status="scheduled",
                )
            )
        s.add(Order(business_id=bid, customer_id=cust.id, reference="CMD-1", status="paid"))
        s.add(
            SupportTicket(
                business_id=bid,
                customer_id=cust.id,
                reference="T-1",
                subject="Retard",
                status="open",
            )
        )
        return cust.id


# ── message entrant ──


@pytest.mark.asyncio
async def test_resolve_customer_no_cascade(client: AsyncClient, db_tables: None) -> None:
    _h, bid = await _auth(client, "resolve@perf.com")
    cid = await _seed_customer(bid)

    async with async_session_factory() as s:
        repo = CustomerRepository(s)
        with count_sql() as stmts:
            by_phone = await repo.find_by_phone(bid, PHONE)
        _report("find_by_phone", stmts)
        assert by_phone is not None and by_phone.id == cid
        assert len(stmts) == 1, stmts

    async with async_session_factory() as s:
        repo = CustomerRepository(s)
        with count_sql() as stmts:
            by_handle = await repo.find_by_handle(bid, HANDLE)
        _report("find_by_handle", stmts)
        assert by_handle is not None and by_handle.id == cid
        assert len(stmts) == 1, stmts

    async with async_session_factory() as s:
        repo = CustomerRepository(s)
        with count_sql() as stmts:
            # email inconnu puis téléphone
            found = await repo.resolve_customer(bid, email="x@y.fr", phone=PHONE)
        _report("resolve_customer", stmts)
        assert found is not None and found.id == cid
        assert found.full_name == "Léa Martin" and found.tags == ["fidèle"]
        assert len(stmts) == 2, stmts
        # autre salon : rien
        assert await repo.find_by_phone(uuid4(), PHONE) is None


@pytest.mark.asyncio
async def test_conversation_repo_no_cascade(client: AsyncClient, db_tables: None) -> None:
    _h, bid = await _auth(client, "convrepo@perf.com")
    cid = await _seed_customer(bid)

    async with async_session_factory() as s:
        repo = ConversationRepository(s)
        with count_sql() as stmts:
            by_ext = await repo.find_by_external_id(bid, "whatsapp", "ext-0")
        _report("find_by_external_id", stmts)
        assert by_ext is not None and by_ext.tags == ["balayage"]
        assert len(stmts) == 1, stmts

        with count_sql() as stmts:
            open_conv = await repo.find_open_for_customer(bid, cid, "instagram")
        _report("find_open_for_customer", stmts)
        assert open_conv is not None and open_conv.external_conversation_id == "ext-1"
        assert len(stmts) == 1, stmts

        with count_sql() as stmts:
            rows = await repo.list_by_business(bid, status="open", limit=10)
        _report("list_by_business", stmts)
        assert len(rows) == 3
        assert len(stmts) == 1, stmts


@pytest.mark.asyncio
async def test_ingest_known_customer(client: AsyncClient, db_tables: None) -> None:
    _h, bid = await _auth(client, "ingest@perf.com")
    cid = await _seed_customer(bid)
    now = datetime.now(UTC)
    msg_in = MessageIn(
        external_message_id="wamid.perf-1",
        external_conversation_id="ext-0",
        channel="whatsapp",
        business_id=bid,
        sender_name="Léa",
        sender_phone=PHONE,
        content_text="Bonjour, je voudrais décaler mon balayage",
        source_created_at=now,
        received_at=now,
    )
    async with async_session_factory() as s, s.begin():
        with count_sql() as stmts:
            ing = await MessageIngestionService(s).ingest(msg_in)
        _report("ingest (cliente connue)", stmts)
        assert ing.customer is not None and ing.customer.id == cid
        assert ing.is_new_customer is False and ing.is_new_conversation is False
        assert ing.conversation.external_conversation_id == "ext-0"
        conv_id = ing.conversation.id
    # aucun historique relu
    assert not any("FROM messages" in q and "messages.conversation_id IN" in q for q in stmts)
    assert len(stmts) <= 9, stmts

    async with async_session_factory() as s:
        conv = await s.get(Conversation, conv_id)
        assert conv.message_count == 9
        assert conv.last_message_preview.startswith("Bonjour")


# ── routes ──


@pytest.mark.asyncio
async def test_superuser_dependency_one_query(client: AsyncClient, db_tables: None) -> None:
    from fastapi import HTTPException

    _h, _bid = await _auth(client, "root@perf.com")
    async with async_session_factory() as s, s.begin():
        await s.execute(update(User).where(User.email == "root@perf.com").values(is_superuser=True))
        uid = (await s.execute(select(User.id).where(User.email == "root@perf.com"))).scalar_one()

    principal = CurrentPrincipal(user_id=uid, business_id=None, email="root@perf.com")
    async with async_session_factory() as s:
        with count_sql() as stmts:
            out = await get_superuser(s, principal)
        _report("get_superuser", stmts)
        assert out is principal
        assert len(stmts) == 1, stmts

    # compte normal ou inconnu : 403
    async with async_session_factory() as s, s.begin():
        await s.execute(update(User).where(User.id == uid).values(is_superuser=False))
    for who in (uid, uuid4()):
        async with async_session_factory() as s:
            with pytest.raises(HTTPException) as exc:
                await get_superuser(s, CurrentPrincipal(user_id=who, business_id=None, email=None))
            assert exc.value.status_code == 403
    # clé API : pas d'utilisateur
    async with async_session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await get_superuser(
                s, CurrentPrincipal(user_id=None, business_id=None, email=None, via_api_key=True)
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_customers_routes_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "fiche@perf.com")
    cid = await _seed_customer(bid)

    with count_sql() as stmts:
        r = await client.get("/api/v1/customers", headers=headers)
    assert r.status_code == 200, r.text
    _report("GET /customers", stmts)
    item = r.json()["customers"][0]
    assert item["full_name"] == "Léa Martin" and item["conversation_count"] == 3
    assert len(stmts) <= 2, stmts

    with count_sql() as stmts:
        r = await client.get(f"/api/v1/customers/{cid}", headers=headers)
    assert r.status_code == 200, r.text
    _report("GET /customers/{id}", stmts)
    d = r.json()
    assert d["stats"]["conversations"] == 3 and d["stats"]["messages"] == 24
    assert d["stats"]["orders"] == 1 and d["stats"]["open_tickets"] == 1
    assert [c["message_count"] for c in d["conversations"]] == [8, 8, 8]
    assert d["orders"][0]["reference"] == "CMD-1"
    assert d["tickets"][0]["subject"] == "Retard"
    assert not any("FROM messages" in q for q in stmts)
    assert len(stmts) <= 8, stmts

    with count_sql() as stmts:
        r = await client.patch(
            f"/api/v1/customers/{cid}",
            headers=headers,
            json={"notes": "aime le café", "tags": ["vip"]},
        )
    assert r.status_code == 200, r.text
    _report("PATCH /customers/{id}", stmts)
    assert r.json()["notes"] == "aime le café" and r.json()["tags"] == ["vip"]
    assert not any("FROM messages" in q for q in stmts)
    assert len(stmts) <= 4, stmts

    with count_sql() as stmts:
        r = await client.get("/api/v1/customers/export.csv", headers=headers)
    assert r.status_code == 200, r.text
    _report("GET /customers/export.csv", stmts)
    assert "Léa Martin" in r.text and "vip" in r.text
    assert len(stmts) <= 1, stmts

    # autre salon : 404
    other_h, _ = await _auth(client, "autre@perf.com")
    r = await client.get(f"/api/v1/customers/{cid}", headers=other_h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_search_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "search@perf.com")
    cid = await _seed_customer(bid)

    with count_sql() as stmts:
        r = await client.get("/api/v1/search", params={"q": "balayage"}, headers=headers)
    assert r.status_code == 200, r.text
    _report("GET /search", stmts)
    d = r.json()
    assert len(d["conversations"]) == 3
    assert {c["customer_name"] for c in d["conversations"]} == {"Léa Martin"}
    assert [a["title"] for a in d["appointments"]] == ["Balayage"] * 3
    assert d["customers"] == []

    with count_sql() as more:
        r = await client.get("/api/v1/search", params={"q": "Léa"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["customers"] == [
        {"id": str(cid), "full_name": "Léa Martin", "email": "lea@client.fr"}
    ]
    assert len(stmts) <= 3, stmts
    assert len(more) <= 3, more

    # autre salon : rien
    other_h, _ = await _auth(client, "autre-search@perf.com")
    r = await client.get("/api/v1/search", params={"q": "balayage"}, headers=other_h)
    assert r.json()["conversations"] == [] and r.json()["appointments"] == []


@pytest.mark.asyncio
async def test_duplicates_do_not_crash_ingestion(client: AsyncClient, db_tables: None) -> None:
    """Doublons (import CSV) : le plus ancien."""
    _h, bid = await _auth(client, "dup@perf.com")
    cid = await _seed_customer(bid)
    later = datetime.now(UTC) + timedelta(minutes=5)
    async with async_session_factory() as s, s.begin():
        # même téléphone, importé après
        s.add(Customer(business_id=bid, full_name="Léa import", phone=PHONE, created_at=later))
        s.add(
            Conversation(
                business_id=bid,
                channel="whatsapp",
                external_conversation_id="ext-0",
                status="open",
                created_at=later,
            )
        )

    async with async_session_factory() as s:
        found = await CustomerRepository(s).find_by_phone(bid, PHONE)
        conv = await ConversationRepository(s).find_by_external_id(bid, "whatsapp", "ext-0")
    assert found is not None and found.id == cid
    assert conv is not None and conv.customer_id == cid

    now = datetime.now(UTC)
    async with async_session_factory() as s, s.begin():
        ing = await MessageIngestionService(s).ingest(
            MessageIn(
                external_message_id="wamid.dup-1",
                external_conversation_id="ext-0",
                channel="whatsapp",
                business_id=bid,
                sender_phone=PHONE,
                content_text="Coucou",
                source_created_at=now,
                received_at=now,
            )
        )
    assert ing.customer.id == cid and ing.conversation.id == conv.id


@pytest.mark.asyncio
async def test_reply_and_assign_query_count(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "reply@perf.com")
    await _seed_customer(bid)
    async with async_session_factory() as s:
        conv_id = (
            await s.execute(
                select(Conversation.id).where(Conversation.external_conversation_id == "ext-0")
            )
        ).scalar_one()
    base = f"/api/v1/conversations/{conv_id}"

    with count_sql() as stmts:
        r = await client.post(f"{base}/reply", headers=headers, json={"text": "Bien reçu !"})
    assert r.status_code == 200, r.text
    _report("POST /conversations/{id}/reply", stmts)
    msg = r.json()["message"]
    assert msg["content"] == "Bien reçu !" and msg["created_at"]
    assert not any("customer_documents" in q for q in stmts)

    with count_sql() as more:
        r = await client.post(f"{base}/assign", headers=headers, json={"assignee": "max@salon.fr"})
    assert r.status_code == 200, r.text
    _report("POST /conversations/{id}/assign", more)
    assert r.json()["assigned_to"] == "max@salon.fr"
    assert not any("FROM businesses" in q for q in more)
