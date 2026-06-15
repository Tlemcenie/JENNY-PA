"""Tests : liste d'attente anti-no-show (#75-#77).

Couvre, sur SQLite réel (pas de mock), sans dépendre des modèles ML ni du LLM :
- le service liste d'attente (inscription, dédoublonnage, rang, re-proposition) ;
- l'action ``join_waitlist`` (inscription depuis le chat) ;
- l'armement moteur : « salon complet » → un « oui » inscrit le client (#76) ;
- la re-proposition automatique à l'annulation/au déplacement (#77), côté client
  (``manage_appointment``) et côté gérant (``owner_assistant``).
"""

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
from jenny.domain.models.waitlist_entry import WaitlistEntry

_CLOSED = {k: None for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


async def _seed_business(*, closed: bool = False) -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(),
            name="Salon Test",
            slug=f"salon-{uuid4().hex[:6]}",
            business_hours=_CLOSED if closed else None,
        )
        s.add(biz)
    return biz


# ── Service liste d'attente ───────────────────────────────────────────────────


class TestWaitlistService:
    @pytest.mark.asyncio
    async def test_add_dedup_and_position(self, db_tables: None) -> None:
        from jenny.services.waitlist_service import add_to_waitlist, waitlist_position

        biz = await _seed_business()
        conv = uuid4()
        async with async_session_factory() as db:
            e1 = await add_to_waitlist(
                db, business_id=biz.id, service="Coupe", conversation_id=conv,
                desired_window="demain", customer_name="Léa",
            )
            # Même conversation + même prestation → pas de doublon.
            e2 = await add_to_waitlist(
                db, business_id=biz.id, service="coupe", conversation_id=conv,
            )
            assert e1.id == e2.id
            # Une autre conversation → 2e place dans la file.
            e3 = await add_to_waitlist(
                db, business_id=biz.id, service="Couleur", conversation_id=uuid4(),
            )
            await db.commit()
            assert await waitlist_position(db, e1) == 1
            assert await waitlist_position(db, e3) == 2

        async with async_session_factory() as db:
            n = (
                await db.execute(select(func.count(WaitlistEntry.id)))
            ).scalar_one()
        assert n == 2

    @pytest.mark.asyncio
    async def test_notify_matches_first_compatible(self, db_tables: None) -> None:
        from jenny.services.waitlist_service import (
            add_to_waitlist,
            notify_waitlist_for_freed_slot,
        )

        biz = await _seed_business()
        async with async_session_factory() as db:
            # File : une attente « Couleur » (ne matche pas), puis une « Coupe ».
            await add_to_waitlist(db, business_id=biz.id, service="Couleur", conversation_id=uuid4())
            coupe = await add_to_waitlist(
                db, business_id=biz.id, service="Coupe", conversation_id=uuid4(),
                customer_name="Marie",
            )
            await db.commit()

        async with async_session_factory() as db:
            notified = await notify_waitlist_for_freed_slot(
                db, business_id=biz.id, service="Coupe", when_label="mardi 14h"
            )
            await db.commit()
            assert notified is not None and notified.id == coupe.id

        async with async_session_factory() as db:
            entry = await db.get(WaitlistEntry, coupe.id)
            assert entry.status == "notified" and entry.notified_at is not None
            notif = (
                await db.execute(
                    select(Notification).where(Notification.kind == "waitlist_match")
                )
            ).scalar_one()
            assert "Marie" in (notif.body or "") and "Coupe" in (notif.body or "")

    @pytest.mark.asyncio
    async def test_notify_returns_none_when_empty(self, db_tables: None) -> None:
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        biz = await _seed_business()
        async with async_session_factory() as db:
            assert await notify_waitlist_for_freed_slot(db, business_id=biz.id) is None


# ── Action d'inscription depuis le chat (#76) ─────────────────────────────────


class TestJoinWaitlistAction:
    @pytest.mark.asyncio
    async def test_execute_creates_entry(self, db_tables: None) -> None:
        from jenny.actions.handlers.join_waitlist import JoinWaitlistAction

        biz = await _seed_business()
        conv = uuid4()
        res = await JoinWaitlistAction().execute(
            {
                "business_id": str(biz.id),
                "conversation_id": str(conv),
                "service": "Coupe",
                "date": "demain matin",
            }
        )
        assert res["success"] and res["waitlisted"] and res["position"] == 1

        async with async_session_factory() as db:
            entry = (
                await db.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id))
            ).scalar_one()
        assert entry.service == "Coupe" and entry.desired_window == "demain matin"
        assert entry.status == "waiting" and str(entry.conversation_id) == str(conv)


# ── Armement moteur : salon complet → « oui » inscrit le client (#76) ─────────


class TestEngineWaitlistOptIn:
    @pytest.mark.asyncio
    async def test_full_salon_then_yes_enrolls(self, db_tables: None) -> None:
        from jenny.engine.conversation_engine import EngineRequest
        from jenny.engine.factory import build_engine
        from jenny.engine.state_manager import StateManager

        biz = await _seed_business(closed=True)  # aucun créneau → no_slots garanti
        sm = StateManager()
        eng = build_engine(state_manager=sm)
        eng.response_generator = None  # pas de LLM : réponses template, test déterministe

        conv, cust = uuid4(), uuid4()

        # Pré-remplit les slots (le slot-filling prestation/jour est testé ailleurs).
        st = sm.get_or_create(conversation_id=conv, business_id=biz.id)
        st.set_slot("service", "Coupe")
        st.set_slot("date", "demain")
        sm.save(st)

        # Tour 1 : tentative de réservation → salon complet.
        r1 = await eng.process(
            EngineRequest(
                conversation_id=conv, business_id=biz.id, customer_id=cust,
                message_text="Je voudrais réserver",
            )
        )
        assert (r1.action_result or {}).get("no_slots") is True
        assert sm.get(conv).awaiting_waitlist is True

        # Tour 2 : « oui » → inscription en liste d'attente.
        r2 = await eng.process(
            EngineRequest(
                conversation_id=conv, business_id=biz.id, customer_id=cust,
                message_text="Oui, avec plaisir",
            )
        )
        assert r2.intent == "join_waitlist"
        assert (r2.action_result or {}).get("waitlisted") is True
        assert sm.get(conv).awaiting_waitlist is False

        async with async_session_factory() as db:
            entry = (
                await db.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == biz.id))
            ).scalar_one()
        assert entry.service == "Coupe" and str(entry.customer_id) == str(cust)


# ── Re-proposition automatique à l'annulation/au déplacement (#77) ────────────


async def _seed_customer_rdv(bid, *, name: str = "Marie", hours_ahead: int = 30) -> tuple:
    start = datetime.now(UTC) + timedelta(hours=hours_ahead)
    async with async_session_factory() as s, s.begin():
        cust = Customer(business_id=bid, full_name=name, email=f"{name.lower()}@x.com")
        s.add(cust)
        await s.flush()
        appt = Appointment(
            business_id=bid, customer_id=cust.id, title="Coupe", channel="chat",
            start_at=start, end_at=start + timedelta(minutes=30),
            status="scheduled", created_by="test",
        )
        s.add(appt)
        await s.flush()
        return cust.id, appt.id


class TestAutoNotifyOnFreeing:
    @pytest.mark.asyncio
    async def test_client_cancel_notifies_waitlist(self, db_tables: None) -> None:
        from jenny.actions.handlers.manage_appointment import ManageAppointmentAction
        from jenny.services.waitlist_service import add_to_waitlist

        biz = await _seed_business()
        cust_id, _appt_id = await _seed_customer_rdv(biz.id)
        async with async_session_factory() as db:
            waiter = await add_to_waitlist(
                db, business_id=biz.id, service="Coupe", conversation_id=uuid4(),
                customer_name="Sonia",
            )
            await db.commit()

        # Le client (propriétaire du RDV) annule → la place se libère.
        res = await ManageAppointmentAction().execute(
            {"business_id": str(biz.id), "customer_id": str(cust_id), "operation": "cancel"}
        )
        assert res["success"] and res["operation"] == "cancel"

        async with async_session_factory() as db:
            entry = await db.get(WaitlistEntry, waiter.id)
            assert entry.status == "notified"
            n = (
                await db.execute(
                    select(func.count(Notification.id)).where(
                        Notification.kind == "waitlist_match"
                    )
                )
            ).scalar_one()
        assert n == 1

    @pytest.mark.asyncio
    async def test_owner_cancel_notifies_waitlist(self, db_tables: None) -> None:
        from jenny.services.owner_assistant import handle_owner_message
        from jenny.services.waitlist_service import add_to_waitlist

        biz = await _seed_business()
        await _seed_customer_rdv(biz.id, name="Marie")
        async with async_session_factory() as db:
            waiter = await add_to_waitlist(
                db, business_id=biz.id, service="Coupe", conversation_id=uuid4(),
                customer_name="Sonia",
            )
            await db.commit()

        async with async_session_factory() as db:
            out = await handle_owner_message(
                db, business_id=biz.id, actor="boss@x.com",
                message="annule le rdv de Marie",
            )
        assert out["data"].get("waitlist_notified") is True

        async with async_session_factory() as db:
            entry = await db.get(WaitlistEntry, waiter.id)
        assert entry.status == "notified"
