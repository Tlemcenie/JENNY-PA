"""Tests e2e : le CLIENT gère son RDV par chat (annuler / déplacer / confirmer).

Via la vraie route /conversation/chat (la détection est par mots-clés, donc
fonctionne sans les modèles ML). Vérifie les écritures réelles en base.
"""

from __future__ import annotations

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
from jenny.domain.models.customer import Customer
from jenny.engine.factory import reset_engine

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client() -> AsyncClient:
    reset_engine()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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


async def _seed_customer_rdv(bid: str, *, hours_ahead: int = 30) -> str:
    start = datetime.now(UTC) + timedelta(hours=hours_ahead)
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=UUID(bid), full_name="Client Test", email="c@x.com")
        s.add(cust)
        await s.flush()
        s.add(
            Appointment(
                business_id=UUID(bid), customer_id=cust.id, title="Coupe", channel="chat",
                start_at=start, end_at=start + timedelta(minutes=30),
                status="scheduled", created_by="test",
            )
        )
        return str(cust.id)


async def _chat(client: AsyncClient, bid: str, cid: str | None, message: str) -> dict:
    body = {"conversation_id": str(uuid4()), "business_id": bid, "message": message}
    if cid:
        body["customer_id"] = cid
    r = await client.post("/api/v1/conversation/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _appt(bid: str) -> Appointment:
    async with async_session_factory() as s:
        return (
            await s.execute(select(Appointment).where(Appointment.business_id == UUID(bid)))
        ).scalar_one()


class TestClientManage:
    @pytest.mark.asyncio
    async def test_cancel(self, client: AsyncClient, db_tables: None) -> None:
        _h, bid = await _auth(client, "s1@x.com")
        cid = await _seed_customer_rdv(bid)
        data = await _chat(client, bid, cid, "Bonjour, je veux annuler mon rendez-vous")
        ar = data["action_result"]
        assert ar and ar.get("operation") == "cancel" and ar.get("success") is True
        assert (await _appt(bid)).status == "cancelled"

    @pytest.mark.asyncio
    async def test_confirm(self, client: AsyncClient, db_tables: None) -> None:
        _h, bid = await _auth(client, "s2@x.com")
        cid = await _seed_customer_rdv(bid)
        data = await _chat(client, bid, cid, "Oui je confirme mon rendez-vous")
        ar = data["action_result"]
        assert ar and ar.get("operation") == "confirm" and ar.get("success") is True
        assert (await _appt(bid)).status == "confirmed"

    @pytest.mark.asyncio
    async def test_reschedule(self, client: AsyncClient, db_tables: None) -> None:
        _h, bid = await _auth(client, "s3@x.com")
        cid = await _seed_customer_rdv(bid)
        original = (await _appt(bid)).start_at
        data = await _chat(client, bid, cid, "Je voudrais déplacer mon rdv à 16h")
        ar = data["action_result"]
        assert ar and ar.get("operation") == "reschedule" and ar.get("success") is True
        # L'action formate le nouveau créneau avant le round-trip SQLite (qui perd
        # le fuseau) : on vérifie là-dessus, et que l'horaire a bien changé.
        assert "16h" in ar.get("when", "")
        assert (await _appt(bid)).start_at != original

    @pytest.mark.asyncio
    async def test_cancel_without_customer_asks_identity(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        _h, bid = await _auth(client, "s4@x.com")
        await _seed_customer_rdv(bid)
        data = await _chat(client, bid, None, "Je veux annuler mon rendez-vous")
        ar = data["action_result"]
        assert ar and ar.get("needs_identification") is True
