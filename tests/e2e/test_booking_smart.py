"""Tests : intelligence de réservation — multi-prestations (#88), anti-double (#87),
capture du nom (#85), client de retour (#86)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


async def _seed(*, with_catalog: bool = True) -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL)
        s.add(biz)
        if with_catalog:
            s.add(Prestation(business_id=biz.id, name="Coupe", price_cents=4000, duration_minutes=30))
            s.add(Prestation(business_id=biz.id, name="Couleur", price_cents=6000, duration_minutes=60))
    return biz


def _tomorrow_word() -> str:
    return "demain"


class TestMultiPrestation:
    @pytest.mark.asyncio
    async def test_two_services_combined(self, db_tables: None) -> None:
        biz = await _seed()
        res = await BookAppointmentDBAction().execute(
            {"business_id": str(biz.id), "service": "coupe et couleur",
             "date": "demain", "time": "10h"}
        )
        assert res["success"], res
        assert res["service"] == "Coupe + Couleur"
        assert res["duration_minutes"] == 90  # 30 + 60
        assert res["price_eur"] == 100.0  # 40 + 60


class TestAntiDouble:
    @pytest.mark.asyncio
    async def test_same_service_same_day_blocked(self, db_tables: None) -> None:
        biz = await _seed()
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name="Léa")
            s.add(cust)
            await s.flush()
            start = datetime.now(UTC) + timedelta(days=1, hours=1)
            # Place le RDV existant à 10h demain.
            tz_start = start.replace(hour=10, minute=0, second=0, microsecond=0)
            s.add(Appointment(
                business_id=biz.id, customer_id=cust.id, title="Coupe", channel="chat",
                start_at=tz_start, end_at=tz_start + timedelta(minutes=30),
                status="scheduled", created_by="Jenny",
            ))
            cid = cust.id

        res = await BookAppointmentDBAction().execute(
            {"business_id": str(biz.id), "customer_id": str(cid), "service": "coupe",
             "date": "demain", "time": "14h"}
        )
        assert res.get("already_booked") is True
        assert res["success"] is False

    @pytest.mark.asyncio
    async def test_different_service_books_with_notice(self, db_tables: None) -> None:
        biz = await _seed()
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name="Léa")
            s.add(cust)
            await s.flush()
            start = (datetime.now(UTC) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
            s.add(Appointment(
                business_id=biz.id, customer_id=cust.id, title="Coupe", channel="chat",
                start_at=start, end_at=start + timedelta(minutes=30),
                status="scheduled", created_by="Jenny",
            ))
            cid = cust.id

        res = await BookAppointmentDBAction().execute(
            {"business_id": str(biz.id), "customer_id": str(cid), "service": "couleur",
             "date": "demain", "time": "14h"}
        )
        assert res["success"] is True
        assert res.get("also_has")  # signalé au client


class TestNameCaptureFlow:
    @pytest.mark.asyncio
    async def test_book_then_name(self, db_tables: None) -> None:
        from jenny.engine.conversation_engine import EngineRequest
        from jenny.engine.factory import build_engine
        from jenny.engine.state_manager import StateManager

        biz = await _seed()
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name=None)  # client SANS nom
            s.add(cust)
            await s.flush()
            cid = cust.id

        sm = StateManager()
        eng = build_engine(state_manager=sm)
        eng.response_generator = None
        conv = uuid4()
        st = sm.get_or_create(conversation_id=conv, business_id=biz.id)
        st.set_slot("service", "Coupe")
        st.set_slot("date", "demain")
        st.set_slot("time", "10h")
        sm.save(st)

        r1 = await eng.process(EngineRequest(
            conversation_id=conv, business_id=biz.id, customer_id=cid,
            message_text="je voudrais réserver",
        ))
        assert (r1.action_result or {}).get("success") is True
        assert (r1.action_result or {}).get("ask_name") is True
        assert sm.get(conv).awaiting_name is True

        r2 = await eng.process(EngineRequest(
            conversation_id=conv, business_id=biz.id, customer_id=cid,
            message_text="Marie",
        ))
        assert r2.intent == "set_customer_name"
        assert (r2.action_result or {}).get("named") is True

        async with async_session_factory() as s:
            cust = await s.get(Customer, cid)
        assert cust.full_name == "Marie"


class TestReturningCustomerContext:
    @pytest.mark.asyncio
    async def test_context_includes_name_and_last_visit(self, db_tables: None) -> None:
        from jenny.services.learning_service import load_customer_context

        biz = await _seed()
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name="Sophie")
            s.add(cust)
            await s.flush()
            past = datetime.now(UTC) - timedelta(days=30)
            s.add(Appointment(
                business_id=biz.id, customer_id=cust.id, title="Balayage", channel="chat",
                start_at=past, end_at=past + timedelta(minutes=90),
                status="completed", created_by="Jenny",
            ))
            cid = cust.id

        async with async_session_factory() as s:
            ctx = await load_customer_context(s, biz.id, cid)
        joined = " ".join(ctx)
        assert "Sophie" in joined
        assert "Balayage" in joined
