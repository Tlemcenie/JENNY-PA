"""au revoir après créneaux proposés : vrai moteur."""

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
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time
from jenny.engine.factory import build_engine
from jenny.engine.state_manager import StateManager

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]
_PARIS = ZoneInfo("Europe/Paris")
_WD = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


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


def _day(n: int):
    return datetime.now(_PARIS).date() + timedelta(days=n)


def _at(n: int, hour: int) -> datetime:
    d = _day(n)
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=_PARIS)


async def _seed(*, block: tuple[int, int, int] | None = None) -> Business:
    """salon + liste d'attente + plage bloquée"""
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon Lina", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL
        )
        s.add(biz)
        s.add(
            Prestation(
                business_id=biz.id, name="Coupe femme", price_cents=3900, duration_minutes=45
            )
        )
        s.add(
            WaitlistEntry(
                business_id=biz.id, service="Coupe femme", customer_name="Léa", status="waiting"
            )
        )
        if block:
            n, h1, h2 = block
            s.add(
                Appointment(
                    business_id=biz.id,
                    title="Pause",
                    status="blocked",
                    start_at=_at(n, h1).astimezone(UTC),
                    end_at=_at(n, h2).astimezone(UTC),
                )
            )
    return biz


async def _client_rdv(biz: Business, n: int, hour: int) -> Customer:
    """client connu avec un rdv"""
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=biz.id, full_name="Marie", phone="+33612345678")
        s.add(cust)
        await s.flush()
        s.add(
            Appointment(
                business_id=biz.id,
                customer_id=cust.id,
                title="Coupe femme",
                start_at=_at(n, hour).astimezone(UTC),
                end_at=(_at(n, hour) + timedelta(minutes=45)).astimezone(UTC),
            )
        )
    return cust


async def _appts(biz: Business) -> list[Appointment]:
    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(Appointment).where(Appointment.business_id == biz.id)))
            .scalars()
            .all()
        )
    return [a for a in rows if a.status not in ("cancelled", "blocked")]


async def _waitlist(biz: Business) -> list[str]:
    async with async_session_factory() as s:
        rows = await s.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id))
        return [e.status for e in rows.scalars().all()]


def _local(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(_PARIS)


class _FixedIntent:
    """modèle qui répond toujours pareil"""

    def __init__(self, intent: str) -> None:
        self.intent = intent

    def predict_multi(self, text: str) -> dict:
        hit = {"intent": self.intent, "confidence": 0.93}
        return {
            "primary_intent": self.intent,
            "primary_confidence": 0.93,
            "intents": [hit],
            "is_multi_intent": False,
            "needs_clarification": False,
        }


class _Chat:
    def __init__(self, biz: Business, model: str | None = None, customer_id=None) -> None:
        self.biz, self.conv, self.customer_id = biz, uuid4(), customer_id
        self.sm = StateManager(redis_url="redis://localhost:1/0")
        self.eng = build_engine(state_manager=self.sm)
        self.eng.response_generator = None  # templates
        if model:
            self.eng.intent_predictor = _FixedIntent(model)

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz.id,
                message_text=msg,
                customer_id=self.customer_id,
                catalog_services=_CATALOG,
                business_name=self.biz.name,
            )
        )


# « à demain » = son rdv actuel
_KEEP_BYES = [
    "Ok tant pis, merci, à demain 10h alors !",
    "Ok merci, à demain alors !",
    "Merci, à demain 10h alors !",
    "Tant pis, merci, à demain !",
    "Non merci, à demain 10h alors !",
    "Merci quand même, à demain 10h !",
]


def _no_move(r) -> None:
    assert r.intent != "manage_appointment"
    assert (r.action_result or {}).get("operation") is None


class TestReportRateAuRevoir:
    @pytest.mark.parametrize("model", [None, "appointment", "closing"])
    @pytest.mark.parametrize("bye", _KEEP_BYES)
    @pytest.mark.asyncio
    async def test_rdv_du_fil_garde(self, db_tables, bye: str, model) -> None:
        # rdv pris ici, report en conflit
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz, model)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        (before,) = await _appts(biz)
        r2 = await chat.say("je voudrais décaler à après-demain 14h")
        assert (r2.action_result or {}).get("conflict") is True
        assert (r2.action_result or {}).get("alternatives_text")
        r3 = await chat.say(bye)
        _no_move(r3)
        (after,) = await _appts(biz)
        assert after.start_at == before.start_at
        # personne prévenu à tort
        assert await _waitlist(biz) == ["waiting"]

    @pytest.mark.parametrize("model", [None, "appointment", "closing"])
    @pytest.mark.parametrize(
        "bye",
        ["Ok merci, à demain 10h alors !", "Ok tant pis, merci, à demain 10h alors !"],
    )
    @pytest.mark.asyncio
    async def test_client_connu_rdv_en_base(self, db_tables, bye: str, model) -> None:
        # rdv hors du fil (whatsapp)
        biz = await _seed(block=(2, 12, 17))
        cust = await _client_rdv(biz, 1, 10)
        chat = _Chat(biz, model, customer_id=cust.id)
        r1 = await chat.say("Je peux décaler à après-demain 14h ?")
        assert (r1.action_result or {}).get("conflict") is True
        r2 = await chat.say(bye)
        _no_move(r2)
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 10)
        assert await _waitlist(biz) == ["waiting"]

    @pytest.mark.asyncio
    async def test_vieux_creneau_pas_rejoue(self, db_tables) -> None:
        # « décale mon rdv » redemande quand
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("je voudrais décaler à après-demain 14h")
        await chat.say("Tant pis, merci, à demain !")
        r = await chat.say("je voudrais décaler mon rdv")
        assert r.intent == "manage_appointment"
        assert (r.action_result or {}).get("need_when") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, 10)
        assert await _waitlist(biz) == ["waiting"]

    @pytest.mark.asyncio
    async def test_vrai_choix_deplace(self, db_tables) -> None:
        # créneau proposé repris : on déplace
        biz = await _seed(block=(2, 12, 17))
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r1 = await chat.say("je voudrais décaler à après-demain 14h")
        alt = (r1.action_result or {})["alternatives_text"].split(",")[0]
        day = parse_fr_date(alt, today=_day(0))
        hour = parse_fr_time(alt)
        assert day and hour
        r2 = await chat.say(
            f"Parfait, à {_WD[day.weekday()]} {hour.hour}h{hour.minute:02d} alors !"
        )
        assert (r2.action_result or {}).get("operation") == "reschedule"
        assert (r2.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert (local.date(), local.hour, local.minute) == (day, hour.hour, hour.minute)


class TestReservationRateeAuRevoir:
    @pytest.mark.parametrize("model", [None, "appointment", "closing"])
    @pytest.mark.parametrize(
        "bye",
        [
            "Tant pis, merci, à demain !",
            "Merci, à demain alors !",
            "Non merci, à demain 10h alors !",
            "Ok tant pis, à demain 10h alors, merci",
        ],
    )
    @pytest.mark.asyncio
    async def test_conflit_puis_au_revoir(self, db_tables, bye: str, model) -> None:
        biz = await _seed(block=(1, 9, 12))
        chat = _Chat(biz, model)
        r1 = await chat.say("je voudrais une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("conflict") is True
        r2 = await chat.say(bye)
        assert r2.intent != "appointment"
        assert await _appts(biz) == []

    @pytest.mark.parametrize("bye", ["Non merci, à demain 10h alors !", "Merci, à demain alors !"])
    @pytest.mark.asyncio
    async def test_propositions_puis_refus(self, db_tables, bye: str) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("propose_slots") is True
        await chat.say(bye)
        assert await _appts(biz) == []

    @pytest.mark.asyncio
    async def test_alternative_choisie_reserve(self, db_tables) -> None:
        biz = await _seed(block=(1, 9, 12))
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain à 10h")
        alt = (r1.action_result or {})["alternatives_text"].split(",")[0]
        hour = parse_fr_time(alt)
        assert hour is not None and parse_fr_date(alt, today=_day(0)) == _day(1)
        r2 = await chat.say(f"Merci, à demain {hour.hour}h{hour.minute:02d} alors !")
        assert (r2.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        assert _local(appt.start_at) == _at(1, hour.hour) + timedelta(minutes=hour.minute)
