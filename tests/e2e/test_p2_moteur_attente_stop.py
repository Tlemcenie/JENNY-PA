"""liste d'attente, STOP, négations : vrai moteur."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.api.routes.webhooks as wh
import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.engine.conversation_engine import STOP_REPLY_TEXT, EngineRequest
from jenny.engine.factory import build_engine
from jenny.engine.response_generator import ResponseGenerator
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


async def _seed(*, full_days: int = 0) -> Business:
    """salon, agenda plein N jours"""
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL
        )
        s.add(biz)
        s.add(
            Prestation(
                business_id=biz.id, name="Coupe femme", price_cents=3900, duration_minutes=45
            )
        )
        today = datetime.now(_PARIS).date()
        for i in range(full_days):
            d = today + timedelta(days=i)
            start = datetime(d.year, d.month, d.day, 8, 0, tzinfo=_PARIS)
            s.add(
                Appointment(
                    business_id=biz.id,
                    title="Fermé",
                    status="blocked",
                    start_at=start.astimezone(UTC),
                    end_at=(start + timedelta(hours=12)).astimezone(UTC),
                )
            )
    return biz


async def _customer(biz_id, name: str = "Marie") -> Customer:
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=biz_id, full_name=name, phone="+33612345678")
        s.add(cust)
    return cust


async def _booked(biz: Business) -> list[Appointment]:
    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(Appointment).where(Appointment.business_id == biz.id)))
            .scalars()
            .all()
        )
    return [a for a in rows if a.status not in ("cancelled", "blocked")]


async def _waitlist(biz: Business) -> list[WaitlistEntry]:
    async with async_session_factory() as s:
        rows = await s.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id))
        return list(rows.scalars().all())


def _local(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(_PARIS)


class _SpyLLM(ResponseGenerator):
    """compte les appels LLM"""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, state, on_token=None) -> str:
        self.calls += 1
        return "réponse du LLM"


class _Chat:
    def __init__(self, biz: Business, customer_id=None) -> None:
        self.biz, self.conv, self.customer_id = biz, uuid4(), customer_id
        self.sm = StateManager(redis_url="redis://localhost:1/0")
        self.eng = build_engine(state_manager=self.sm)
        self.llm = _SpyLLM()
        self.eng.response_generator = self.llm

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz.id,
                message_text=msg,
                customer_id=self.customer_id,
                catalog_services=_CATALOG,
            )
        )


class TestListeAttente:
    @pytest.mark.asyncio
    async def test_creneau_choisi_apres_complet_est_reserve(self, db_tables) -> None:
        # complet → autre jour → « Ok 14h »
        biz = await _seed(full_days=16)
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("no_slots") is True
        target = datetime.now(_PARIS).date() + timedelta(days=20)
        r2 = await chat.say(f"Et le {target.day} ?")
        assert (r2.action_result or {}).get("propose_slots") is True
        assert chat.sm.get(chat.conv).awaiting_waitlist is False
        r3 = await chat.say("Ok 14h")
        assert r3.intent == "appointment"
        assert (r3.action_result or {}).get("success") is True
        (appt,) = await _booked(biz)
        local = _local(appt.start_at)
        assert local.date() == target and local.hour == 14
        assert await _waitlist(biz) == []

    @pytest.mark.asyncio
    async def test_merci_quand_meme_n_inscrit_pas(self, db_tables) -> None:
        biz = await _seed(full_days=16)
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("no_slots") is True
        await chat.say("Je vais réfléchir")
        r3 = await chat.say("Super, merci quand même")
        assert r3.intent != "join_waitlist"
        assert await _waitlist(biz) == []

    @pytest.mark.asyncio
    async def test_oui_inscrit(self, db_tables) -> None:
        biz = await _seed(full_days=16)
        chat = _Chat(biz)
        await chat.say("je voudrais une coupe femme demain")
        r = await chat.say("oui")
        assert r.intent == "join_waitlist"
        (entry,) = await _waitlist(biz)
        assert entry.status == "waiting"


class TestStop:
    @pytest.mark.parametrize("stop", ["STOP", "stop", "Stop.", "désinscription"])
    @pytest.mark.asyncio
    async def test_client_connu_desinscrit(self, db_tables, stop: str) -> None:
        biz = await _seed()
        cust = await _customer(biz.id)
        chat = _Chat(biz, customer_id=cust.id)
        r = await chat.say(stop)
        assert r.response_text == STOP_REPLY_TEXT
        assert r.intent == "opt_out"
        # pas de LLM
        assert chat.llm.calls == 0
        async with async_session_factory() as s:
            fresh = await s.get(Customer, cust.id)
        assert fresh.marketing_opt_out_at is not None

    @pytest.mark.asyncio
    async def test_anonyme_rien_de_special(self, db_tables) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r = await chat.say("STOP")
        assert r.intent != "opt_out"
        assert r.response_text != STOP_REPLY_TEXT

    @pytest.mark.asyncio
    async def test_client_d_un_autre_salon(self, db_tables) -> None:
        biz, other = await _seed(), await _seed()
        cust = await _customer(other.id)
        chat = _Chat(biz, customer_id=cust.id)
        r = await chat.say("STOP")
        assert r.intent != "opt_out"
        async with async_session_factory() as s:
            fresh = await s.get(Customer, cust.id)
        assert fresh.marketing_opt_out_at is None

    @pytest.mark.asyncio
    async def test_stop_dans_une_phrase(self, db_tables) -> None:
        biz = await _seed()
        cust = await _customer(biz.id)
        chat = _Chat(biz, customer_id=cust.id)
        r = await chat.say("stop, je voulais dire jeudi")
        assert r.intent != "opt_out"
        async with async_session_factory() as s:
            fresh = await s.get(Customer, cust.id)
        assert fresh.marketing_opt_out_at is None

    @pytest.mark.asyncio
    async def test_stop_whatsapp(self, db_tables, monkeypatch) -> None:
        # vrai webhook, vrai moteur
        biz = await _seed()
        eng = build_engine(state_manager=StateManager(redis_url="redis://localhost:1/0"))
        eng.response_generator = None
        async def _engine():
            return eng

        monkeypatch.setattr(wh, "_get_engine", _engine)
        sent: list[str] = []

        async def _send(recipient: str, content: str, **_kw) -> bool:
            sent.append(content)
            return True

        monkeypatch.setattr(wh._whatsapp, "send_reply", _send)
        phone = "33611223344"
        msg = {
            "from": phone,
            "id": f"wamid.{uuid4().hex[:8]}",
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "STOP"},
        }
        await wh._whatsapp_ingest_and_reply(msg, str(biz.id), {phone: "Marie"})
        assert sent == [STOP_REPLY_TEXT]
        async with async_session_factory() as s:
            cust = (
                await s.execute(select(Customer).where(Customer.business_id == biz.id))
            ).scalar_one()
        assert cust.marketing_opt_out_at is not None


class TestFuseau:
    @pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])
    @pytest.mark.asyncio
    async def test_demain_au_fuseau_du_salon(self, db_tables, tz: str) -> None:
        from jenny.engine.datetime_fr import today_in

        biz = await _seed()
        async with async_session_factory() as s, s.begin():
            (await s.get(Business, biz.id)).timezone = tz
        chat = _Chat(biz)
        chat.eng.response_generator = None
        r = await chat.eng.process(
            EngineRequest(
                conversation_id=chat.conv,
                business_id=biz.id,
                message_text="je réserve une coupe femme demain à 10h",
                catalog_services=_CATALOG,
                timezone=tz,
            )
        )
        assert (r.action_result or {}).get("success") is True
        (appt,) = await _booked(biz)
        start = appt.start_at if appt.start_at.tzinfo else appt.start_at.replace(tzinfo=UTC)
        local = start.astimezone(ZoneInfo(tz))
        assert local.date() == today_in(tz) + timedelta(days=1)
        assert local.hour == 10


class TestNegations:
    @pytest.mark.parametrize(
        ("answer", "weekday"),
        [
            ("Pourquoi pas samedi ?", 5),
            ("Jeudi c'est pas un problème", 3),
            ("samedi ça me va pas mal", 5),
        ],
    )
    @pytest.mark.asyncio
    async def test_oui_a_un_jour_garde_la_date(self, db_tables, answer: str, weekday: int) -> None:
        biz = await _seed()
        chat = _Chat(biz)
        r1 = await chat.say("je veux un rdv pour une coupe femme")
        assert r1.clarification_reason == "slot_filling"
        r2 = await chat.say(answer)
        assert r2.intent == "appointment"
        assert (r2.action_result or {}).get("propose_slots") is True
        day = chat.sm.get(chat.conv).slots["date"].value
        assert datetime.fromisoformat(day).weekday() == weekday
