"""Résa en ligne : coiffeur pas compétent."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff, StaffSkill

_PARIS = ZoneInfo("Europe/Paris")
_HOURS = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


def _at(hour: int) -> str:
    d: date = (datetime.now(_PARIS) + timedelta(days=3)).date()
    return datetime(d.year, d.month, d.day, hour, tzinfo=_PARIS).astimezone(UTC).isoformat()


async def test_coiffeur_pas_competent_message_clair(db_tables) -> None:
    async with async_session_factory() as s, s.begin():
        b = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_HOURS)
        s.add(b)
        await s.flush()
        coupe = Prestation(id=uuid4(), business_id=b.id, name="Coupe homme", price_cents=2500)
        colo = Prestation(id=uuid4(), business_id=b.id, name="Coloration", price_cents=6000)
        marc = Staff(id=uuid4(), business_id=b.id, display_name="Marc", all_services=False)
        s.add_all([coupe, colo, marc])
        await s.flush()
        s.add(StaffSkill(staff_id=marc.id, prestation_id=coupe.id))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        body = {
            "full_name": "Dina",
            "email": "dina@x.com",
            "start_at": _at(14),
            "prestation_id": str(colo.id),
            "staff_id": str(marc.id),
        }
        r = await c.post(f"/api/v1/public/booking/{b.slug}/book", json=body)
        assert r.status_code == 400
        assert "Marc ne réalise pas cette prestation" in r.json()["detail"]
        # sa prestation passe
        body["prestation_id"] = str(coupe.id)
        r = await c.post(f"/api/v1/public/booking/{b.slug}/book", json=body)
        assert r.status_code == 201


async def test_rdv_chat_garde_sa_conversation(db_tables) -> None:
    """L'acompte se retrouve par le fil."""
    from sqlalchemy import select

    from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
    from jenny.domain.models.appointment import Appointment

    async with async_session_factory() as s, s.begin():
        b = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_HOURS)
        s.add(b)
    conv = uuid4()
    day = (datetime.now(_PARIS) + timedelta(days=3)).date().isoformat()
    res = await BookAppointmentDBAction().execute(
        {
            "business_id": str(b.id),
            "conversation_id": str(conv),
            "service": "Coupe",
            "date": day,
            "time": "10:00",
        }
    )
    assert res["success"] is True
    async with async_session_factory() as s:
        appt = (await s.execute(select(Appointment))).scalar_one()
    assert appt.conversation_id == conv
