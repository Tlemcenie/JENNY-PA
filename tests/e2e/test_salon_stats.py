"""Tests : statistiques métier du salon (#79)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
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


@pytest.mark.asyncio
async def test_stats_empty_business(client: AsyncClient, db_tables: None) -> None:
    headers, _bid = await _auth(client, "empty@salon.com")
    r = await client.get("/api/v1/salon/stats", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["appointments_total"] == 0 and data["clients_total"] == 0
    assert data["top_prestations"] == [] and data["waitlist"]["waiting"] == 0


@pytest.mark.asyncio
async def test_stats_aggregates(client: AsyncClient, db_tables: None) -> None:
    headers, bid = await _auth(client, "stats@salon.com")
    buid = UUID(bid)
    now = datetime.now(UTC)
    async with async_session_factory() as s, s.begin():
        # Catalogue : Coupe à 40€.
        s.add(Prestation(business_id=buid, name="Coupe", price_cents=4000, duration_minutes=30))
        # Cliente fidèle (2 RDV honorés passés) + 1 RDV à venir.
        a = Customer(business_id=buid, full_name="Alice")
        b = Customer(business_id=buid, full_name="Bob")
        s.add_all([a, b])
        await s.flush()

        def _appt(cid, hours, status, title="Coupe", dep=None):
            start = now + timedelta(hours=hours)
            ap = Appointment(
                business_id=buid, customer_id=cid, title=title, channel="chat",
                start_at=start, end_at=start + timedelta(minutes=30),
                status=status, created_by="test",
            )
            if dep:
                ap.deposit_cents, ap.deposit_status = dep
            return ap

        s.add_all([
            _appt(a.id, -72, "confirmed"),            # passé honoré
            _appt(a.id, -48, "completed"),            # passé honoré → Alice fidèle
            _appt(b.id, -24, "cancelled"),            # passé annulé
            _appt(a.id, 24, "scheduled", dep=(1200, "paid")),   # à venir + acompte payé
            _appt(b.id, 48, "scheduled", dep=(1000, "pending")),  # à venir + acompte en attente
        ])
        s.add(WaitlistEntry(business_id=buid, service="Coupe", status="waiting", conversation_id=uuid4()))

    r = await client.get("/api/v1/salon/stats", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["upcoming"] == 2
    assert d["cancelled"] == 1
    assert d["clients_total"] == 2 and d["loyal_clients"] == 1 and d["new_clients"] == 1
    assert d["top_prestations"][0]["name"] == "Coupe"
    assert d["revenue_upcoming_eur"] == 80.0  # 2 RDV Coupe à venir x 40€
    assert d["deposits"]["paid"] == 1 and d["deposits"]["pending"] == 1
    assert d["deposits"]["collected_eur"] == 12.0
    assert d["waitlist"]["waiting"] == 1
    assert 0.0 <= d["cancellation_rate_pct"] <= 100.0
