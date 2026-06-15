"""Tests : RGPD — export (#81) et anonymisation (#82) des données client."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.customer_address import CustomerAddress
from jenny.domain.models.customer_fact import CustomerFact
from jenny.domain.models.message import Message
from jenny.domain.models.waitlist_entry import WaitlistEntry

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


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


async def _auth(client: AsyncClient, email: str) -> tuple[dict, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Salon", "email": email, "password": _PASSWORD},
    )
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


async def _seed_customer(bid: UUID) -> UUID:
    now = datetime.now(UTC)
    async with async_session_factory() as s, s.begin():
        cust = Customer(
            business_id=bid, full_name="Marie Curie", email="marie@x.com",
            phone="0600000000", notes="VIP",
        )
        s.add(cust)
        await s.flush()
        start = now + timedelta(days=1)
        s.add(Appointment(
            business_id=bid, customer_id=cust.id, title="Coupe", channel="chat",
            start_at=start, end_at=start + timedelta(minutes=30),
            status="scheduled", created_by="Jenny",
        ))
        s.add(CustomerFact(
            business_id=bid, customer_id=cust.id, fact="Allergique à l'ammoniaque.",
            fact_key="allergie", kind="constraint",
        ))
        s.add(CustomerAddress(
            business_id=bid, customer_id=cust.id, label="Domicile", line1="1 rue de la Paix",
            city="Paris", postal_code="75001", country="FR",
        ))
        conv = Conversation(
            business_id=bid, customer_id=cust.id, channel="chat", status="open",
            message_count=1, last_message_at=now,
        )
        s.add(conv)
        await s.flush()
        s.add(Message(
            business_id=bid, customer_id=cust.id, conversation_id=conv.id,
            external_message_id=str(uuid4()),
            channel="chat", direction="inbound", content_text="Bonjour, je veux un RDV",
            sender_name="Marie", sender_email="marie@x.com", status="received",
            received_at=now,
        ))
        s.add(WaitlistEntry(
            business_id=bid, customer_id=cust.id, service="Couleur",
            customer_name="Marie", customer_contact="0600000000", status="waiting",
        ))
        return cust.id


class TestExport:
    @pytest.mark.asyncio
    async def test_export_bundle(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "exp@salon.com")
        cid = await _seed_customer(UUID(bid))
        r = await client.get(f"/api/v1/customers/{cid}/export", headers=headers)
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers.get("content-disposition", "")
        bundle = json.loads(r.content)
        assert bundle["profile"]["full_name"] == "Marie Curie"
        assert bundle["counts"]["appointments"] == 1
        assert bundle["counts"]["facts"] == 1
        assert bundle["counts"]["messages"] == 1
        assert bundle["counts"]["addresses"] == 1
        assert bundle["counts"]["waitlist"] == 1

    @pytest.mark.asyncio
    async def test_export_other_business_404(self, client: AsyncClient, db_tables: None) -> None:
        _h1, _bid1 = await _auth(client, "a@salon.com")
        headers2, _bid2 = await _auth(client, "b@salon.com")
        cid = await _seed_customer(UUID(_bid1))
        # Le business B ne peut pas exporter le client du business A.
        r = await client.get(f"/api/v1/customers/{cid}/export", headers=headers2)
        assert r.status_code == 404


class TestAnonymize:
    @pytest.mark.asyncio
    async def test_anonymize_scrubs_pii(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "anon@salon.com")
        buid = UUID(bid)
        cid = await _seed_customer(buid)

        r = await client.post(f"/api/v1/customers/{cid}/anonymize", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["anonymized"] is True
        assert body["deleted"]["addresses"] == 1 and body["deleted"]["facts"] == 1
        assert body["scrubbed_messages"] == 1

        async with async_session_factory() as s:
            cust = await s.get(Customer, cid)
            assert cust.full_name == "Client anonymisé"
            assert cust.email is None and cust.phone is None and cust.notes is None
            assert cust.anonymized_at is not None
            facts = (await s.execute(select(CustomerFact).where(CustomerFact.customer_id == cid))).scalars().all()
            assert facts == []
            addrs = (await s.execute(select(CustomerAddress).where(CustomerAddress.customer_id == cid))).scalars().all()
            assert addrs == []
            msg = (await s.execute(select(Message).where(Message.customer_id == cid))).scalar_one()
            assert "supprimé" in msg.content_text and msg.sender_email is None
            wl = (await s.execute(select(WaitlistEntry).where(WaitlistEntry.customer_id == cid))).scalar_one()
            assert wl.status == "cancelled" and wl.customer_contact is None
            # Le RDV (comptabilité) est conservé.
            appt = (await s.execute(select(Appointment).where(Appointment.customer_id == cid))).scalar_one()
            assert appt is not None

    @pytest.mark.asyncio
    async def test_anonymize_idempotent(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "anon2@salon.com")
        cid = await _seed_customer(UUID(bid))
        r1 = await client.post(f"/api/v1/customers/{cid}/anonymize", headers=headers)
        assert r1.json()["anonymized"] is True
        r2 = await client.post(f"/api/v1/customers/{cid}/anonymize", headers=headers)
        assert r2.json().get("already_anonymized") is True
