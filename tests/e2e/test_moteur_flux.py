"""flux moteur sur vraie base."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
from jenny.engine import conversation_engine as ce
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import build_engine
from jenny.engine.state_manager import StateManager

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]
_PARIS = ZoneInfo("Europe/Paris")


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


async def _seed() -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL
        )
        s.add(biz)
        for name, cents, minutes in (
            ("Coupe femme", 3900, 45),
            ("Coupe homme", 2500, 30),
            ("Balayage", 8000, 120),
        ):
            s.add(
                Prestation(
                    business_id=biz.id, name=name, price_cents=cents, duration_minutes=minutes
                )
            )
    return biz


async def _appts(biz: Business) -> list[Appointment]:
    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(Appointment).where(Appointment.business_id == biz.id)))
            .scalars()
            .all()
        )
    return [a for a in rows if a.status != "cancelled"]


def _local(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(_PARIS)


class _Chat:
    def __init__(self, biz: Business) -> None:
        self.biz, self.conv = biz, uuid4()
        self.sm = StateManager(redis_url="redis://localhost:1/0")
        self.eng = build_engine(state_manager=self.sm)
        self.eng.response_generator = None  # templates

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz.id,
                message_text=msg,
                catalog_services=_CATALOG,
            )
        )


class TestApresReservation:
    @pytest.mark.asyncio
    async def test_aussi_un_balayage_pas_a_l_ancienne_date(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        r2 = await chat.say("je voudrais aussi réserver un balayage")
        # demande le jour, pas l'ancien créneau
        assert not (r2.action_result or {}).get("conflict")
        assert r2.clarification_reason == "slot_filling"
        assert len(await _appts(biz)) == 1

    @pytest.mark.asyncio
    async def test_parfait_merci_ne_confirme_pas(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        await chat.say("Parfait, merci !")
        (appt,) = await _appts(biz)
        assert appt.status == "scheduled"

    @pytest.mark.asyncio
    async def test_cest_bon_cest_marie_garde_le_nom(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("ask_name") is True
        r2 = await chat.say("C'est bon, c'est Marie")
        assert r2.intent == "set_customer_name"
        (appt,) = await _appts(biz)
        assert appt.status == "scheduled"
        async with async_session_factory() as s:
            cust = await s.get(Customer, appt.customer_id)
        assert cust is not None and cust.full_name == "Marie"

    @pytest.mark.asyncio
    async def test_oui_confirme_vraiment(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("oui")
        assert (r.action_result or {}).get("operation") == "confirm"
        (appt,) = await _appts(biz)
        assert appt.status == "confirmed"


class TestDatesAbsoluesBase:
    @pytest.mark.asyncio
    async def test_minuit_ne_decale_pas(self, db_tables, monkeypatch) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je veux réserver une coupe femme demain")
        tomorrow = datetime.now(_PARIS).date() + timedelta(days=1)
        assert chat.sm.get(chat.conv).slots["date"].value == tomorrow.isoformat()
        # on passe minuit partout
        import jenny.actions.handlers.book_appointment_db as bdb
        import jenny.engine.datetime_fr as dtf

        fake_now = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 5, tzinfo=_PARIS)

        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now.astimezone(tz) if tz else fake_now.replace(tzinfo=None)

        monkeypatch.setattr(bdb, "datetime", _Clock)
        monkeypatch.setattr(dtf, "datetime", _Clock)
        monkeypatch.setattr(ce, "today_in", lambda tz=None: tomorrow)
        r = await chat.say("à 15h")
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert local.date() == tomorrow and local.hour == 15

    @pytest.mark.asyncio
    async def test_dans_quinze_jours(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r = await chat.say("je réserve une coupe homme dans 15 jours à 11h")
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert local.date() == datetime.now(_PARIS).date() + timedelta(days=14)
        assert local.hour == 11

    @pytest.mark.asyncio
    async def test_jeudi_prochain_midi(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r = await chat.say("je réserve un balayage jeudi prochain à midi")
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        today = datetime.now(_PARIS).date()
        next_monday = today + timedelta(days=7 - today.weekday())
        assert local.date() == next_monday + timedelta(days=3)
        assert (local.hour, local.minute) == (12, 0)
