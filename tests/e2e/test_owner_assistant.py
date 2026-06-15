"""Tests e2e : assistant du coiffeur (Jenny côté gérant).

Vérifie que le gérant peut, par chat, obtenir un compte rendu, bloquer un
créneau, et ajouter une info — avec de VRAIES écritures en base (SQLite).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

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

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client() -> AsyncClient:
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
        json={"full_name": "Gérant", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


async def _seed_appt(bid: str, *, hours_ahead: int, status: str = "confirmed") -> None:
    now = datetime.now(UTC)
    start = now + timedelta(hours=hours_ahead)
    async with async_session_factory() as s, s.begin():
        s.add(
            Appointment(
                business_id=UUID(bid),
                title="Coupe",
                channel="chat",
                start_at=start,
                end_at=start + timedelta(minutes=30),
                status=status,
                created_by="test",
            )
        )


class TestOwnerAssistant:
    @pytest.mark.asyncio
    async def test_report(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "boss@salon.com")
        await _seed_appt(bid, hours_ahead=2, status="confirmed")
        await _seed_appt(bid, hours_ahead=4, status="scheduled")
        r = await client.post(
            "/api/v1/owner/chat", headers=headers, json={"message": "Combien j'ai de rendez-vous ?"}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["action"] == "report"
        assert data["data"]["upcoming"] == 2
        assert data["data"]["confirmed"] == 1

    @pytest.mark.asyncio
    async def test_block_slot(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "boss2@salon.com")
        r = await client.post(
            "/api/v1/owner/chat",
            headers=headers,
            json={"message": "Bloque mardi prochain de 14h à 16h s'il te plaît"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "block_slot"
        # Un créneau bloqué a bien été créé en base.
        async with async_session_factory() as s:
            rows = (
                await s.execute(
                    select(Appointment).where(
                        Appointment.business_id == UUID(bid),
                        Appointment.status == "blocked",
                    )
                )
            ).scalars().all()
        assert len(rows) == 1
        assert (rows[0].end_at - rows[0].start_at) == timedelta(hours=2)

    @pytest.mark.asyncio
    async def test_add_knowledge(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "boss3@salon.com")
        r = await client.post(
            "/api/v1/owner/chat",
            headers=headers,
            json={"message": "Note que le parking est gratuit pour nos clients"},
        )
        assert r.status_code == 200, r.text
        # Intention bien reconnue (l'enregistrement vectoriel peut être indispo sous SQLite).
        assert r.json()["action"] == "add_knowledge"
        assert "parking" in r.json()["response"].lower() or "noté" in r.json()["response"].lower()

    @pytest.mark.asyncio
    async def test_agenda_today(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "boss5@salon.com")
        # Midi du jour COURANT dans le fuseau du salon (Europe/Paris), comme le fait
        # l'agenda : sinon, entre 22h et minuit UTC, la date UTC et la date de Paris
        # divergent et le RDV tomberait hors de la fenêtre du jour.
        from zoneinfo import ZoneInfo

        paris = ZoneInfo("Europe/Paris")
        today = datetime.now(paris).date()
        noon = datetime(today.year, today.month, today.day, 12, 0, tzinfo=paris).astimezone(UTC)
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=UUID(bid), full_name="Léa Bernard")
            s.add(cust)
            await s.flush()
            s.add(
                Appointment(
                    business_id=UUID(bid), customer_id=cust.id, title="Coupe",
                    channel="chat", start_at=noon, end_at=noon + timedelta(minutes=30),
                    status="scheduled", created_by="test",
                )
            )
        r = await client.post(
            "/api/v1/owner/chat", headers=headers, json={"message": "Qui vient aujourd'hui ?"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "agenda"
        assert r.json()["data"]["count"] == 1
        assert "Léa" in r.json()["response"]

    @pytest.mark.asyncio
    async def test_cancel_by_name(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "boss6@salon.com")
        start = datetime.now(UTC) + timedelta(hours=30)
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=UUID(bid), full_name="Marie Martin")
            s.add(cust)
            await s.flush()
            s.add(
                Appointment(
                    business_id=UUID(bid), customer_id=cust.id, title="Coloration",
                    channel="chat", start_at=start, end_at=start + timedelta(minutes=90),
                    status="scheduled", created_by="test",
                )
            )
        r = await client.post(
            "/api/v1/owner/chat", headers=headers, json={"message": "Annule le rdv de Marie"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "cancel"
        async with async_session_factory() as s:
            appt = (
                await s.execute(select(Appointment).where(Appointment.business_id == UUID(bid)))
            ).scalar_one()
        assert appt.status == "cancelled"

    @pytest.mark.asyncio
    async def test_general_question(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "boss4@salon.com")
        r = await client.post(
            "/api/v1/owner/chat", headers=headers, json={"message": "Salut Jenny, ça va ?"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "general"
        assert len(r.json()["response"]) > 0
