"""Tests : acompte anti-no-show (#78).

Sur SQLite réel, sans Stripe configuré → mode manuel (suivi 100 % réel en base,
encaissement à la main). Couvre : calcul du montant, ouverture de l'acompte,
intégration à la réservation, et passage « payé » (service + API → RDV confirmé).
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
from jenny.domain.models.business import Business
from jenny.domain.models.payment_record import PaymentRecord
from jenny.engine.factory import reset_engine

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
    reset_engine()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


async def _seed_business(*, deposit: bool, percent: int = 30, hours: dict | None = None) -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}",
            business_hours=hours, deposit_enabled=deposit, deposit_percent=percent,
            deposit_min_cents=1000,
        )
        s.add(biz)
    return biz


# ── Calcul du montant ─────────────────────────────────────────────────────────


class TestComputeDeposit:
    def test_percent_of_price(self) -> None:
        from jenny.services.deposit_service import compute_deposit_cents

        biz = Business(deposit_enabled=True, deposit_percent=30, deposit_min_cents=1000)
        assert compute_deposit_cents(biz, 40.0) == 1200  # 30 % de 40€
        assert compute_deposit_cents(biz, None) == 1000  # forfait sans prix

    def test_disabled_returns_none(self) -> None:
        from jenny.services.deposit_service import compute_deposit_cents

        biz = Business(deposit_enabled=False, deposit_percent=30, deposit_min_cents=1000)
        assert compute_deposit_cents(biz, 40.0) is None


# ── Ouverture de l'acompte (mode manuel) ──────────────────────────────────────


class TestCreateDeposit:
    @pytest.mark.asyncio
    async def test_manual_mode_records_pending(self, db_tables: None) -> None:
        from jenny.services.deposit_service import create_deposit_for_appointment

        biz = await _seed_business(deposit=True)
        start = datetime.now(UTC) + timedelta(days=1)
        async with async_session_factory() as db:
            appt = Appointment(
                business_id=biz.id, title="Coupe", channel="chat",
                start_at=start, end_at=start + timedelta(minutes=30),
                status="scheduled", created_by="Jenny",
            )
            db.add(appt)
            await db.flush()
            business = await db.get(Business, biz.id)
            out = await create_deposit_for_appointment(
                db, business=business, appointment=appt, price_eur=40.0, service_name="Coupe"
            )
            await db.commit()
            appt_id = appt.id

        assert out and out["amount_cents"] == 1200 and out["mode"] == "manual"
        assert out["checkout_url"] is None  # pas de Stripe → pas de lien

        async with async_session_factory() as db:
            appt = await db.get(Appointment, appt_id)
            assert appt.deposit_status == "pending" and appt.deposit_cents == 1200
            pay = (await db.execute(select(PaymentRecord))).scalar_one()
            assert pay.status == "pending" and pay.amount_minor == 1200
            assert pay.metadata_["kind"] == "deposit"


# ── Intégration à la réservation depuis le chat ───────────────────────────────


class TestBookingWithDeposit:
    @pytest.mark.asyncio
    async def test_booking_creates_deposit(self, db_tables: None) -> None:
        from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction

        biz = await _seed_business(deposit=True, hours=_OPEN_ALL)
        res = await BookAppointmentDBAction().execute(
            {
                "business_id": str(biz.id),
                "service": "Coupe",
                "date": "demain",
                "time": "10h",
            }
        )
        assert res["success"] is True, res
        dep = res.get("deposit")
        assert dep and dep["amount_cents"] == 1000  # pas de prix catalogue → forfait 10€

        async with async_session_factory() as db:
            appt = await db.get(Appointment, UUID(res["appointment_id"]))
            assert appt.deposit_status == "pending" and appt.deposit_payment_id is not None

    @pytest.mark.asyncio
    async def test_booking_without_policy_has_no_deposit(self, db_tables: None) -> None:
        from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction

        biz = await _seed_business(deposit=False, hours=_OPEN_ALL)
        res = await BookAppointmentDBAction().execute(
            {"business_id": str(biz.id), "service": "Coupe", "date": "demain", "time": "11h"}
        )
        assert res["success"] is True and res.get("deposit") is None


# ── Passage « payé » → RDV confirmé ───────────────────────────────────────────


class TestMarkPaid:
    @pytest.mark.asyncio
    async def test_service_marks_paid_and_confirms(self, db_tables: None) -> None:
        from jenny.services.deposit_service import (
            create_deposit_for_appointment,
            mark_deposit_paid_by_payment,
        )

        biz = await _seed_business(deposit=True)
        start = datetime.now(UTC) + timedelta(days=1)
        async with async_session_factory() as db:
            appt = Appointment(
                business_id=biz.id, title="Couleur", channel="chat",
                start_at=start, end_at=start + timedelta(minutes=60),
                status="scheduled", created_by="Jenny",
            )
            db.add(appt)
            await db.flush()
            business = await db.get(Business, biz.id)
            await create_deposit_for_appointment(
                db, business=business, appointment=appt, price_eur=60.0
            )
            await db.commit()
            appt_id = appt.id

        async with async_session_factory() as db:
            pay = (await db.execute(select(PaymentRecord))).scalar_one()
            confirmed = await mark_deposit_paid_by_payment(db, payment=pay)
            await db.commit()
            assert confirmed is not None and confirmed.id == appt_id

        async with async_session_factory() as db:
            appt = await db.get(Appointment, appt_id)
            assert appt.deposit_status == "paid" and appt.status == "confirmed"

    @pytest.mark.asyncio
    async def test_api_mark_paid(self, client: AsyncClient, db_tables: None) -> None:
        # Salon + acompte demandé, via un RDV réel.
        from jenny.services.deposit_service import create_deposit_for_appointment

        email = "boss@salon.com"
        r = await client.post(
            "/api/v1/auth/register",
            json={"full_name": "Boss", "email": email, "password": _PASSWORD},
        )
        code = r.json()["debug_code"]
        rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
        headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
        bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]

        start = datetime.now(UTC) + timedelta(days=1)
        async with async_session_factory() as db:
            biz = await db.get(Business, UUID(bid))
            biz.deposit_enabled = True
            appt = Appointment(
                business_id=UUID(bid), title="Coupe", channel="chat",
                start_at=start, end_at=start + timedelta(minutes=30),
                status="scheduled", created_by="Jenny",
            )
            db.add(appt)
            await db.flush()
            await create_deposit_for_appointment(
                db, business=biz, appointment=appt, price_eur=40.0
            )
            await db.commit()
            appt_id = str(appt.id)

        resp = await client.post(
            f"/api/v1/appointments/{appt_id}/deposit/mark-paid", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deposit_status"] == "paid" and body["status"] == "confirmed"
