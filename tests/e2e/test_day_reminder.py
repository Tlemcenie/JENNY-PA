"""Test : rappel « la veille » du cron de balayage (RDV dans les 24h)."""

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
async def test_day_before_reminder_once(db_tables: None) -> None:
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"s-{uuid4().hex[:6]}"))
        start = datetime.now(UTC) + timedelta(hours=20)  # dans 24h, hors de l'heure
        s.add(
            Appointment(
                business_id=bid, title="Coupe", channel="chat", start_at=start,
                end_at=start + timedelta(minutes=30), status="scheduled",
                created_by="boss@x.com",
            )
        )

    res = await sweep_conversations({})
    assert int(res["day_reminded"]) == 1

    async with async_session_factory() as s:
        n = (
            await s.execute(
                select(func.count(Notification.id)).where(
                    Notification.kind == "appointment_reminder_day"
                )
            )
        ).scalar_one()
        appt = (await s.execute(select(Appointment))).scalar_one()
    assert n == 1
    assert appt.day_reminder_sent_at is not None

    # Idempotent : un second balayage ne renvoie pas le rappel.
    res2 = await sweep_conversations({})
    assert int(res2["day_reminded"]) == 0
