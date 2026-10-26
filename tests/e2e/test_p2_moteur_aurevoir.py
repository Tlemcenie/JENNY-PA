"""au revoir et noms, vrai moteur sur base."""

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


async def _seed(*, waitlist: bool = False) -> Business:
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
        if waitlist:
            s.add(
                WaitlistEntry(
                    business_id=biz.id, service="Coupe femme", customer_name="Léa", status="waiting"
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


async def _customers(biz: Business) -> list[Customer]:
    async with async_session_factory() as s:
        rows = await s.execute(select(Customer).where(Customer.business_id == biz.id))
        return list(rows.scalars().all())


async def _waitlist_status(biz: Business) -> list[str]:
    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id)))
            .scalars()
            .all()
        )
    return [e.status for e in rows]


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
    def __init__(self, biz: Business, model: str | None = None) -> None:
        self.biz, self.conv = biz, uuid4()
        self.sm = StateManager(redis_url="redis://localhost:1/0")
        self.eng = build_engine(state_manager=self.sm)
        self.eng.response_generator = None  # templates
        if model:
            # simule un modèle qui se trompe
            self.eng.intent_predictor = _FixedIntent(model)

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz.id,
                message_text=msg,
                catalog_services=_CATALOG,
                business_name=self.biz.name,
            )
        )


_BYES = [
    "Merci, bon week-end !",
    "Bon week-end !",
    "Merci, à la semaine prochaine !",
    "À ce soir !",
    "Merci, à ce soir 18h !",
    "Merci, à demain !",
    "merci, à demain 😊",
    "À demain 10h !",
    "Bonne soirée !",
    "Bon dimanche !",
    "À mardi en huit !",
    "Merci beaucoup, à vendredi !",
    "À demain pour mon rendez-vous !",
    "à demain, merci encore",
]


class TestAuRevoirNeDeplacePas:
    @pytest.mark.parametrize("model", [None, "appointment", "closing"])
    @pytest.mark.parametrize("bye", _BYES)
    @pytest.mark.asyncio
    async def test_rdv_et_liste_attente_intacts(self, db_tables, bye: str, model) -> None:
        biz = await _seed(waitlist=True)
        chat = _Chat(biz, model)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        (before,) = await _appts(biz)
        r2 = await chat.say(bye)
        assert r2.intent != "manage_appointment"
        assert (r2.action_result or {}).get("operation") is None
        (after,) = await _appts(biz)
        assert after.start_at == before.start_at
        # personne prévenu à tort
        assert await _waitlist_status(biz) == ["waiting"]

    @pytest.mark.asyncio
    async def test_vrai_report_deplace(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("plutôt après-demain à 11h")
        assert (r.action_result or {}).get("operation") == "reschedule"
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert local.date() == datetime.now(_PARIS).date() + timedelta(days=2)
        assert local.hour == 11

    @pytest.mark.parametrize("bye", ["Bon week-end à vous !", "À ce soir !", "À demain !"])
    @pytest.mark.asyncio
    async def test_au_revoir_en_cours_ne_reserve_pas(self, db_tables, bye: str) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je veux un rdv à 15h pour une coupe femme")
        await chat.say(bye)
        assert await _appts(biz) == []

    @pytest.mark.asyncio
    async def test_creneau_propose_puis_a_demain_11h(self, db_tables) -> None:
        # « à demain 11h » choisit le créneau
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("propose_slots") is True
        r2 = await chat.say("Parfait, à demain 11h alors !")
        assert (r2.action_result or {}).get("success") is True
        (appt,) = await _appts(biz)
        local = _local(appt.start_at)
        assert local.date() == datetime.now(_PARIS).date() + timedelta(days=1)
        assert local.hour == 11


class TestNomPasMerci:
    @pytest.mark.parametrize(
        "polite", ["Merci beaucoup !", "merci infiniment", "Merci Jenny !", "madame", "Jenny"]
    )
    @pytest.mark.asyncio
    async def test_politesse_puis_vrai_nom(self, db_tables, polite: str) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("ask_name") is True
        r2 = await chat.say(polite)
        assert r2.intent != "set_customer_name"
        (appt,) = await _appts(biz)
        assert appt.customer_id is None
        assert await _customers(biz) == []
        r3 = await chat.say("Marie")
        assert r3.intent == "set_customer_name"
        (appt,) = await _appts(biz)
        async with async_session_factory() as s:
            cust = await s.get(Customer, appt.customer_id)
        assert cust is not None and cust.full_name == "Marie"

    @pytest.mark.parametrize(
        ("msg", "name"),
        [
            ("Super merci beaucoup, Marie Dupont", "Marie Dupont"),
            ("Merci beaucoup, je m'appelle Marie", "Marie"),
            ("C'est Marie, merci infiniment !", "Marie"),
        ],
    )
    @pytest.mark.asyncio
    async def test_vrai_nom_avec_merci_garde(self, db_tables, msg: str, name: str) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say(msg)
        assert r.intent == "set_customer_name"
        (cust,) = await _customers(biz)
        assert cust.full_name == name

    @pytest.mark.asyncio
    async def test_je_confirme_cest_marie(self, db_tables) -> None:
        # confirmé ET nom gardé
        biz = await _seed()
        chat = _Chat(biz)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("Je confirme, c'est Marie")
        assert r.intent == "set_customer_name"
        assert (r.action_result or {}).get("confirmed") is True
        (appt,) = await _appts(biz)
        assert appt.status == "confirmed"
        async with async_session_factory() as s:
            cust = await s.get(Customer, appt.customer_id)
        assert cust is not None and cust.full_name == "Marie"
        assert chat.sm.get(chat.conv).awaiting_confirmation is False
