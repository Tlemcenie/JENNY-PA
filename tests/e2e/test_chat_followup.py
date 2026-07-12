"""Tests de SUIVI conversationnel (bugs trouvés par la batterie adversariale).

Chaque test pinne une propriété de continuité multi-tours du moteur, contre une
vraie DB (SQLite) avec catalogue de prestations :
- override RDV « prestation + jour/heure » sans mot-clé « réserver » ;
- override RDV sur « complaint » mal classé (sauf vrai signal de réclamation) ;
- report IMPLICITE : un nouveau créneau après un RDV pris déplace CE rdv ;
- reprise de réservation après une question (prix) au milieu du flux.
"""

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
from jenny.engine.conversation_engine import (
    _COMPLAINT_SIGNAL_RE,
    _STRONG_APPOINTMENT_RE,
    EngineRequest,
)
from jenny.engine.factory import build_engine
from jenny.engine.state_manager import StateManager

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_CATALOG = ["Coupe femme", "Coupe homme", "Balayage", "Coloration"]


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
        s.add(
            Prestation(
                business_id=biz.id, name="Coupe femme", price_cents=3900, duration_minutes=45
            )
        )
        s.add(
            Prestation(
                business_id=biz.id, name="Coupe homme", price_cents=2500, duration_minutes=30
            )
        )
        s.add(
            Prestation(business_id=biz.id, name="Balayage", price_cents=8000, duration_minutes=120)
        )
    return biz


def _req(conv, biz, msg, cid=None):
    return EngineRequest(
        conversation_id=conv,
        business_id=biz.id,
        customer_id=cid,
        message_text=msg,
        catalog_services=_CATALOG,
    )


class TestComplaintSignalGating:
    """Un « complaint » mal classé ne doit pas bloquer l'override RDV, sauf vrai
    signal de mécontentement."""

    def test_booking_phrase_has_no_complaint_signal(self) -> None:
        assert _STRONG_APPOINTMENT_RE.search("je réserve une coupe femme mardi")
        assert not _COMPLAINT_SIGNAL_RE.search("je réserve une coupe femme mardi")

    def test_real_complaint_detected(self) -> None:
        assert _COMPLAINT_SIGNAL_RE.search("je veux réserver mais votre dernière coupe était ratée")
        assert _COMPLAINT_SIGNAL_RE.search("je demande un remboursement")
        assert _COMPLAINT_SIGNAL_RE.search("c'est inadmissible, je suis déçu")


class TestServiceWhenOverride:
    """« [prestation] [jour] [heure] » sans mot-clé réserve quand même."""

    @pytest.mark.asyncio
    async def test_service_plus_when_books(self, db_tables) -> None:
        biz = await _seed()
        sm = StateManager()
        eng = build_engine(state_manager=sm)
        eng.response_generator = None
        conv = uuid4()
        r = await eng.process(_req(conv, biz, "une coupe femme demain à 14h"))
        assert r.intent == "appointment"
        assert (r.action_result or {}).get("success") is True
        async with async_session_factory() as s:
            n = await s.scalar(select(Appointment.id).where(Appointment.business_id == biz.id))
        assert n is not None  # RDV réellement créé


class TestImplicitReschedule:
    """Après un RDV pris, un nouveau créneau seul déplace CE rdv (sans mot-clé)."""

    @pytest.mark.asyncio
    async def test_new_slot_reschedules_existing(self, db_tables) -> None:
        biz = await _seed()
        sm = StateManager()
        eng = build_engine(state_manager=sm)
        eng.response_generator = None
        conv = uuid4()

        # 1) Réserve coupe femme demain 10h.
        r1 = await eng.process(_req(conv, biz, "je réserve une coupe femme demain à 10h"))
        assert (r1.action_result or {}).get("success") is True
        appt_id = (r1.action_result or {}).get("appointment_id")
        assert appt_id

        # 2) « après-demain 15h » (nouveau créneau, AUCUN mot-clé « déplacer ») →
        #    doit DÉPLACER le rdv, pas en créer un second ni répondre à côté.
        r2 = await eng.process(_req(conv, biz, "en fait après-demain à 15h"))
        assert r2.intent == "manage_appointment"
        assert (r2.action_result or {}).get("operation") == "reschedule"
        assert (r2.action_result or {}).get("success") is True

        async with async_session_factory() as s:
            rows = (
                (await s.execute(select(Appointment).where(Appointment.business_id == biz.id)))
                .scalars()
                .all()
            )
        # UN SEUL rdv (déplacé), pas deux.
        active = [a for a in rows if a.status not in ("cancelled",)]
        assert len(active) == 1
        tz = ZoneInfo("Europe/Paris")
        moved = active[0].start_at
        moved = moved if moved.tzinfo else moved.replace(tzinfo=UTC)
        local = moved.astimezone(tz)
        assert local.hour == 15  # heure mise à jour
        assert local.date() == (datetime.now(tz) + timedelta(days=2)).date()  # après-demain

    @pytest.mark.asyncio
    async def test_new_service_is_not_a_reschedule(self, db_tables) -> None:
        # Un message qui cite une NOUVELLE prestation n'est pas un report : c'est
        # une (éventuelle) nouvelle demande — on ne déplace pas le rdv existant.
        biz = await _seed()
        sm = StateManager()
        eng = build_engine(state_manager=sm)
        eng.response_generator = None
        conv = uuid4()
        r1 = await eng.process(_req(conv, biz, "je réserve une coupe femme demain à 10h"))
        assert (r1.action_result or {}).get("success") is True
        r2 = await eng.process(_req(conv, biz, "et un balayage vendredi ?"))
        # NE doit PAS être un reschedule de la coupe femme.
        assert (r2.action_result or {}).get("operation") != "reschedule"
