"""Tests : garde-fous de réservation et capture de contact en chat anonyme.

Couvre les bugs révélés par les conversations longues du 2026-07-11 :
- réservation d'un créneau déjà passé (« samedi 10h » dit le samedi soir),
- déplacement vers un jour de fermeture hebdomadaire (lundi),
- fiche client créée à la volée (nom puis téléphone) et rattachée au RDV,
- gestion du RDV de la conversation sans identification (appointment_id).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.actions.handlers.manage_appointment import ManageAppointmentAction
from jenny.actions.handlers.set_customer_name import SetCustomerNameAction
from jenny.actions.handlers.set_customer_phone import SetCustomerPhoneAction, extract_phone
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.services.availability import is_day_closed

_OPEN_TUE_SAT = {k: ["09:00", "19:00"] for k in ("tue", "wed", "thu", "fri", "sat")}


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


async def _seed_business() -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(),
            name="Salon",
            slug=f"s-{uuid4().hex[:6]}",
            business_hours=_OPEN_TUE_SAT,  # fermé dimanche ET lundi
        )
        s.add(biz)
    return biz


def _next_weekday(base: datetime, weekday: int) -> datetime:
    days = (weekday - base.weekday()) % 7 or 7
    return base + timedelta(days=days)


class TestPastSlotGuard:
    async def test_booking_in_the_past_is_refused(self, db_tables) -> None:
        biz = await _seed_business()
        now = datetime.now(UTC)
        if now.hour == 0:  # « il y a une heure » traverserait minuit
            pytest.skip("fenêtre minuit : l'heure passée d'aujourd'hui serait hier")
        past_hour = f"{now.astimezone().hour - 1}h00" if now.astimezone().hour >= 1 else "0h00"
        result = await BookAppointmentDBAction().execute(
            {
                "business_id": str(biz.id),
                "service": "coupe",
                "date": "aujourd'hui",
                "time": past_hour,
            }
        )
        # Jour ouvré → refus « passé » ; jour fermé (dim/lun) → refus « fermé ».
        assert result["success"] is False
        assert result.get("past") or result.get("closed")
        async with async_session_factory() as s:
            from sqlalchemy import func, select

            n = await s.scalar(select(func.count(Appointment.id)))
        assert n == 0  # rien n'a été réservé


class TestWeeklyClosure:
    async def test_is_day_closed_covers_weekly_closure(self, db_tables) -> None:
        biz = await _seed_business()
        now = datetime.now(UTC)
        monday = _next_weekday(now, 0).date()
        tuesday = _next_weekday(now, 1).date()
        async with async_session_factory() as s:
            assert await is_day_closed(s, biz.id, monday) is True
            assert await is_day_closed(s, biz.id, tuesday) is False

    async def test_reschedule_to_closed_day_is_refused(self, db_tables) -> None:
        biz = await _seed_business()
        start = _next_weekday(datetime.now(UTC), 1).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        async with async_session_factory() as s, s.begin():
            appt = Appointment(
                id=uuid4(),
                business_id=biz.id,
                title="Coupe",
                channel="chat",
                start_at=start,
                end_at=start + timedelta(minutes=30),
                status="scheduled",
                created_by="Jenny",
            )
            s.add(appt)
        result = await ManageAppointmentAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "operation": "reschedule",
                # « lundi prochain » (pas « lundi ») : garanti FUTUR même si le test
                # tourne un lundi après-midi — sinon la cible tombe dans le passé et
                # c'est « past » (et non « closed ») qui est renvoyé.
                "date": "lundi prochain",
                "time": "14h",
            }
        )
        assert result["success"] is False
        assert result.get("closed") is True
        async with async_session_factory() as s:
            fresh = await s.get(Appointment, appt.id)
        # SQLite stocke naïf : on normalise avant de comparer.
        stored = fresh.start_at if fresh.start_at.tzinfo else fresh.start_at.replace(tzinfo=UTC)
        assert stored == start  # rien n'a bougé


class TestAnonymousContactCapture:
    async def _seed_appt(self, biz: Business) -> Appointment:
        start = _next_weekday(datetime.now(UTC), 2).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        async with async_session_factory() as s, s.begin():
            appt = Appointment(
                id=uuid4(),
                business_id=biz.id,
                title="Coupe femme",
                channel="chat",
                start_at=start,
                end_at=start + timedelta(minutes=45),
                status="scheduled",
                created_by="Jenny",
            )
            s.add(appt)
        return appt

    async def test_name_creates_customer_and_attaches(self, db_tables) -> None:
        biz = await _seed_business()
        appt = await self._seed_appt(biz)
        result = await SetCustomerNameAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "name": "emma dupont",
            }
        )
        assert result["success"] is True
        assert result["name"] == "Emma Dupont"
        assert result["ask_phone"] is True
        async with async_session_factory() as s:
            fresh = await s.get(Appointment, appt.id)
            assert fresh.customer_id is not None
            cust = await s.get(Customer, fresh.customer_id)
            assert cust.full_name == "Emma Dupont"

    async def test_phone_saved_on_customer(self, db_tables) -> None:
        biz = await _seed_business()
        appt = await self._seed_appt(biz)
        named = await SetCustomerNameAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "name": "Emma Dupont",
            }
        )
        result = await SetCustomerPhoneAction().execute(
            {
                "business_id": str(biz.id),
                "customer_id": named["customer_id"],
                "phone": "06 12 34 56 78",
            }
        )
        assert result == {"success": True, "phoned": True, "phone": "0612345678"}
        async with async_session_factory() as s:
            cust_id = named["customer_id"]
            from uuid import UUID

            cust = await s.get(Customer, UUID(cust_id))
        assert cust.phone == "0612345678"

    async def test_confirm_via_conversation_appointment(self, db_tables) -> None:
        biz = await _seed_business()
        appt = await self._seed_appt(biz)
        result = await ManageAppointmentAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "operation": "confirm",
            }
        )
        assert result["success"] is True
        async with async_session_factory() as s:
            fresh = await s.get(Appointment, appt.id)
        assert fresh.status == "confirmed"


class TestPhoneExtraction:
    def test_extracts_common_formats(self) -> None:
        assert extract_phone("0612345678") == "0612345678"
        assert extract_phone("c'est le 06 12 34 56 78 !") == "0612345678"
        assert extract_phone("+33 6 12 34 56 78") == "+33612345678"

    def test_rejects_non_phones(self) -> None:
        assert extract_phone("demain à 14h30") is None
        assert extract_phone("j'ai 2 enfants") is None
        assert extract_phone("") is None
