"""Tests : suivi post-RDV — avis + relance de re-réservation (#83, cron ARQ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.workers.tasks import sweep_conversations


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


@pytest.mark.asyncio
async def test_post_visit_review_request(db_tables: None) -> None:
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"s-{uuid4().hex[:6]}"))
        start = datetime.now(UTC) - timedelta(hours=2)  # terminé il y a ~90 min
        s.add(Appointment(
            business_id=bid, title="Coupe", channel="chat", start_at=start,
            end_at=start + timedelta(minutes=30), status="completed", created_by="boss@x.com",
        ))

    res = await sweep_conversations({})
    assert int(res["review_asked"]) == 1

    async with async_session_factory() as s:
        n = (await s.execute(
            select(func.count(Notification.id)).where(Notification.kind == "review_request")
        )).scalar_one()
        appt = (await s.execute(select(Appointment))).scalar_one()
    assert n == 1 and appt.review_request_sent_at is not None

    # Idempotent.
    res2 = await sweep_conversations({})
    assert int(res2["review_asked"]) == 0


@pytest.mark.asyncio
async def test_rebook_reminder_when_no_upcoming(db_tables: None) -> None:
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"s-{uuid4().hex[:6]}"))
        cust = Customer(business_id=bid, full_name="Alice")
        s.add(cust)
        await s.flush()
        old = datetime.now(UTC) - timedelta(days=50)  # dernier RDV il y a 50 jours
        s.add(Appointment(
            business_id=bid, customer_id=cust.id, title="Couleur", channel="chat",
            start_at=old, end_at=old + timedelta(minutes=60), status="completed",
            created_by="boss@x.com",
        ))

    res = await sweep_conversations({})
    assert int(res["rebook_nudged"]) == 1

    async with async_session_factory() as s:
        n = (await s.execute(
            select(func.count(Notification.id)).where(Notification.kind == "rebook_reminder")
        )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_no_rebook_if_upcoming_exists(db_tables: None) -> None:
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"s-{uuid4().hex[:6]}"))
        cust = Customer(business_id=bid, full_name="Bob")
        s.add(cust)
        await s.flush()
        old = datetime.now(UTC) - timedelta(days=50)
        s.add(Appointment(
            business_id=bid, customer_id=cust.id, title="Coupe", channel="chat",
            start_at=old, end_at=old + timedelta(minutes=30), status="completed",
            created_by="boss@x.com",
        ))
        # Bob a déjà un RDV à venir → pas de relance.
        soon = datetime.now(UTC) + timedelta(days=3)
        s.add(Appointment(
            business_id=bid, customer_id=cust.id, title="Coupe", channel="chat",
            start_at=soon, end_at=soon + timedelta(minutes=30), status="scheduled",
            created_by="boss@x.com",
        ))

    res = await sweep_conversations({})
    assert int(res["rebook_nudged"]) == 0
    async with async_session_factory() as s:
        n = (await s.execute(
            select(func.count(Notification.id)).where(Notification.kind == "rebook_reminder")
        )).scalar_one()
    assert n == 0
