"""Tests : lot salon v2 — fermetures (#89), rappels config (#90), no-show (#91),
avis (#92), fidélité (#93), notes RDV (#94), historique client owner (#95)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
from jenny.domain.models.business import Business
from jenny.domain.models.business_closure import BusinessClosure
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
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


# ── #89 Fermetures exceptionnelles ────────────────────────────────────────────


class TestClosures:
    @pytest.mark.asyncio
    async def test_closed_day_has_no_slots(self, db_tables: None) -> None:
        from jenny.services.availability import free_slots_for_day, is_day_closed

        async with async_session_factory() as s, s.begin():
            biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL)
            s.add(biz)
            tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
            s.add(BusinessClosure(business_id=biz.id, start_date=tomorrow, end_date=tomorrow, reason="Congé"))
            bid = biz.id

        async with async_session_factory() as db:
            assert await is_day_closed(db, bid, tomorrow) is True
            slots = await free_slots_for_day(db, bid, tomorrow, 30)
        assert slots == []

    @pytest.mark.asyncio
    async def test_closures_crud_api(self, client: AsyncClient, db_tables: None) -> None:
        headers, _bid = await _auth(client, "clo@salon.com")
        r = await client.post(
            "/api/v1/salon/closures", headers=headers,
            json={"start_date": "2026-08-01", "end_date": "2026-08-15", "reason": "Vacances"},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        lst = await client.get("/api/v1/salon/closures", headers=headers)
        assert len(lst.json()) == 1
        d = await client.delete(f"/api/v1/salon/closures/{cid}", headers=headers)
        assert d.status_code == 200
        assert (await client.get("/api/v1/salon/closures", headers=headers)).json() == []


# ── #90 Rappels configurables ─────────────────────────────────────────────────


class TestReminderConfig:
    @pytest.mark.asyncio
    async def test_custom_lead_triggers_reminder(self, db_tables: None) -> None:
        from jenny.workers.tasks import sweep_conversations

        async with async_session_factory() as s, s.begin():
            # Délai imminent porté à 2h → un RDV dans 90 min déclenche le rappel.
            biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", reminder_lead_minutes=120)
            s.add(biz)
            start = datetime.now(UTC) + timedelta(minutes=90)
            s.add(Appointment(
                business_id=biz.id, title="Coupe", channel="chat", start_at=start,
                end_at=start + timedelta(minutes=30), status="scheduled", created_by="boss@x.com",
            ))

        res = await sweep_conversations({})
        assert int(res["reminded"]) == 1


# ── #91 No-show + acompte forcé ───────────────────────────────────────────────


class TestNoShow:
    @pytest.mark.asyncio
    async def test_recidivist_forces_deposit(self, db_tables: None) -> None:
        from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction

        async with async_session_factory() as s, s.begin():
            # Acompte DÉSACTIVÉ au niveau salon.
            biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}",
                           business_hours=_OPEN_ALL, deposit_enabled=False)
            s.add(biz)
            s.add(Prestation(business_id=biz.id, name="Coupe", price_cents=4000, duration_minutes=30))
            cust = Customer(business_id=biz.id, full_name="Kevin")
            s.add(cust)
            await s.flush()
            # 2 lapins passés.
            past = datetime.now(UTC) - timedelta(days=10)
            for _ in range(2):
                s.add(Appointment(
                    business_id=biz.id, customer_id=cust.id, title="Coupe", channel="chat",
                    start_at=past, end_at=past + timedelta(minutes=30), status="no_show", created_by="Jenny",
                ))
            bid, cid = biz.id, cust.id

        res = await BookAppointmentDBAction().execute(
            {"business_id": str(bid), "customer_id": str(cid), "service": "coupe",
             "date": "demain", "time": "10h"}
        )
        assert res["success"] is True
        assert res["deposit"] is not None and res["deposit"]["forced"] is True

    @pytest.mark.asyncio
    async def test_mark_no_show_via_api(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "ns@salon.com")
        start = datetime.now(UTC) - timedelta(hours=2)
        async with async_session_factory() as s, s.begin():
            appt = Appointment(business_id=UUID(bid), title="Coupe", channel="chat",
                               start_at=start, end_at=start + timedelta(minutes=30),
                               status="scheduled", created_by="Jenny")
            s.add(appt)
            await s.flush()
            aid = str(appt.id)
        r = await client.patch(f"/api/v1/appointments/{aid}", headers=headers, json={"status": "no_show"})
        assert r.status_code == 200 and r.json()["status"] == "no_show"


# ── #92 Avis + #93 Fidélité + #94 Notes ───────────────────────────────────────


class TestReviewsLoyaltyNotes:
    @pytest.mark.asyncio
    async def test_review_then_stats(self, client: AsyncClient, db_tables: None) -> None:
        headers, _bid = await _auth(client, "rev@salon.com")
        for rating in (5, 4):
            r = await client.post("/api/v1/salon/reviews", headers=headers,
                                   json={"rating": rating, "comment": "Top"})
            assert r.status_code == 201, r.text
        stats = await client.get("/api/v1/salon/stats", headers=headers)
        d = stats.json()
        assert d["reviews_count"] == 2
        assert d["average_rating"] == 4.5

    @pytest.mark.asyncio
    async def test_loyalty_points(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "loy@salon.com")
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=UUID(bid), full_name="Fidèle")
            s.add(cust)
            await s.flush()
            past = datetime.now(UTC) - timedelta(days=5)
            for _ in range(3):
                s.add(Appointment(business_id=UUID(bid), customer_id=cust.id, title="Coupe",
                                  channel="chat", start_at=past, end_at=past + timedelta(minutes=30),
                                  status="completed", created_by="Jenny"))
            cid = str(cust.id)
        r = await client.get(f"/api/v1/salon/loyalty/{cid}", headers=headers)
        assert r.status_code == 200
        assert r.json()["points"] == 3 and r.json()["threshold"] == 10

    @pytest.mark.asyncio
    async def test_staff_notes(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "notes@salon.com")
        start = datetime.now(UTC) + timedelta(days=1)
        async with async_session_factory() as s, s.begin():
            appt = Appointment(business_id=UUID(bid), title="Couleur", channel="chat",
                               start_at=start, end_at=start + timedelta(minutes=60),
                               status="scheduled", created_by="Jenny")
            s.add(appt)
            await s.flush()
            aid = str(appt.id)
        r = await client.patch(f"/api/v1/appointments/{aid}", headers=headers,
                               json={"staff_notes": "Couleur 6.3 + oxydant 20vol"})
        assert r.status_code == 200
        assert r.json()["staff_notes"] == "Couleur 6.3 + oxydant 20vol"


# ── #95 Historique client (assistant coiffeur) ────────────────────────────────


class TestOwnerClientHistory:
    @pytest.mark.asyncio
    async def test_history_by_name(self, db_tables: None) -> None:
        from jenny.services.owner_assistant import handle_owner_message

        async with async_session_factory() as s, s.begin():
            biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", loyalty_threshold=3)
            s.add(biz)
            cust = Customer(business_id=biz.id, full_name="Marie Dupont")
            s.add(cust)
            await s.flush()
            past = datetime.now(UTC) - timedelta(days=20)
            for _ in range(3):
                s.add(Appointment(business_id=biz.id, customer_id=cust.id, title="Balayage",
                                  channel="chat", start_at=past, end_at=past + timedelta(minutes=90),
                                  status="completed", created_by="Jenny"))
            bid = biz.id

        async with async_session_factory() as db:
            out = await handle_owner_message(db, business_id=bid, actor="boss@x.com",
                                             message="montre-moi l'historique de Marie")
        assert out["action"] == "client_history"
        assert out["data"]["found"] is True
        assert "Marie" in out["response"]
        assert out["data"]["points"] == 3
