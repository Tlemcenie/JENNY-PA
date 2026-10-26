"""oui explicite + jour : liste d'attente, vrai moteur."""

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


async def _seed_full() -> Business:
    """salon plein 16 jours"""
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
        for i in range(16):
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


async def _waitlist(biz: Business) -> list[WaitlistEntry]:
    async with async_session_factory() as s:
        rows = await s.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id))
        return list(rows.scalars().all())


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


class TestOuiAvecLeJour:
    @pytest.mark.parametrize(
        "msg",
        [
            "Oui, inscrivez-moi pour demain",
            "Oui, prévenez-moi si demain se libère",
            "Volontiers, mettez-moi pour demain",
        ],
    )
    @pytest.mark.asyncio
    async def test_oui_meme_jour_inscrit(self, db_tables, msg: str) -> None:
        biz = await _seed_full()
        chat = _Chat(biz)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("no_slots") is True
        r2 = await chat.say(msg)
        assert r2.intent == "join_waitlist"
        (entry,) = await _waitlist(biz)
        assert entry.status == "waiting"

    @pytest.mark.parametrize(
        "msg", ["Ok, demain alors", "Oui mais plutôt après-demain", "Oui, demain 14h"]
    )
    @pytest.mark.asyncio
    async def test_autre_cas_pas_inscrit(self, db_tables, msg: str) -> None:
        # ack seul, autre jour, heure
        biz = await _seed_full()
        chat = _Chat(biz)
        await chat.say("je voudrais une coupe femme demain")
        r = await chat.say(msg)
        assert r.intent != "join_waitlist"
        assert await _waitlist(biz) == []
