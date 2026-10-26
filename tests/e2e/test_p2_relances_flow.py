"""Relances passe 2, sur SQLite réel.

Prénom piégé, STOP appliqué partout, liste d'attente sans fuite de nom
et tracée dans slot_offers, passe après suppression, boucle de fond.
Seuls l'envoi SMS / WhatsApp et le test Redis sont simulés.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import Campaign, SlotOffer
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services import campaigns as camp_svc
from jenny.services import gap_filler, relances_loop

_OPEN = {k: ["00:00", "23:59"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


@pytest.fixture
def sms(monkeypatch) -> list[tuple[str, str]]:
    """SMS simulé : tout part."""
    sent: list[tuple[str, str]] = []

    async def fake(self, to, body):
        sent.append((to, body))
        return SimpleNamespace(success=True)

    monkeypatch.setattr("jenny.notifications.sms_sender.SmsSender.send_sms", fake)
    return sent


@pytest.fixture
def no_redis(monkeypatch) -> None:
    """Prod démo : pas de Redis."""
    from jenny.core.config import get_settings

    monkeypatch.setattr(get_settings(), "redis_url", "")
    monkeypatch.setattr(gap_filler, "in_send_hours", lambda b, n: True)


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


def _now() -> datetime:
    return datetime.now(UTC)


async def _biz(name: str = "Salon Zoé") -> Business:
    async with async_session_factory() as s, s.begin():
        b = Business(id=uuid4(), name=name, slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN)
        s.add(b)
    return b


async def _cust(biz, name: str, *, phone: str | None = "+33600000000", **kw) -> Customer:
    async with async_session_factory() as s, s.begin():
        c = Customer(id=uuid4(), business_id=biz.id, full_name=name, phone=phone, **kw)
        s.add(c)
    return c


async def _appt(biz, cust, start: datetime, *, status="completed", minutes=30, title="Coupe"):
    async with async_session_factory() as s, s.begin():
        a = Appointment(
            id=uuid4(),
            business_id=biz.id,
            customer_id=cust.id if cust else None,
            title=title,
            start_at=start,
            end_at=start + timedelta(minutes=minutes),
            status=status,
        )
        s.add(a)
    return a


async def _dormante(biz, name: str, **kw) -> Customer:
    c = await _cust(biz, name, **kw)
    for d in (200, 120):
        await _appt(biz, c, _now() - timedelta(days=d))
    return c


def _auth(biz) -> dict[str, str]:
    token = create_access_token(uuid4(), "gerant@test.fr", [biz.id])
    return {"Authorization": f"Bearer {token}"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ── prénom avec antislash ──


class TestPrenomPiege:
    async def test_campagne_part_a_toutes(self, db_tables, sms) -> None:
        biz = await _biz()
        await _dormante(biz, "\\o/ Lucie", phone="+33600000001")
        await _dormante(biz, "Lu\\cie", phone="+33600000002")
        await _dormante(biz, "Marie", phone="+33600000003")
        async with async_session_factory() as db:
            camp = await camp_svc.create_campaign(
                db, business_id=biz.id, segment="dormants", message="Bonjour {prenom}, ça va ?"
            )
            await db.commit()
            res = await camp_svc.deliver_campaign(db, camp.id)
        assert res["sent"] == 3 and len(sms) == 3
        texts = sorted(t for _to, t in sms)
        assert any(t.startswith("Bonjour Marie, ça va ?") for t in texts)
        async with async_session_factory() as db:
            c = await db.get(Campaign, camp.id)
        assert c.status == "sent" and c.sent_count == 3

    async def test_rendu_route_200(self, db_tables, client) -> None:
        biz = await _biz()
        r = await client.post(
            "/api/v1/campaigns/render",
            json={"message": "Coucou {prenom} !", "name": "\\o/"},
            headers=_auth(biz),
        )
        assert r.status_code == 200, r.text
        assert r.json()["text"].startswith("Coucou !")

    async def test_une_cliente_qui_plante_ne_bloque_pas(self, db_tables, monkeypatch) -> None:
        biz = await _biz()
        await _dormante(biz, "Anna", phone="+33600000001")
        await _dormante(biz, "Bea", phone="+33600000002")
        sent: list[str] = []

        async def fake(self, to, body):
            if to.endswith("1"):
                raise RuntimeError("canal HS")
            sent.append(to)
            return SimpleNamespace(success=True)

        monkeypatch.setattr("jenny.notifications.sms_sender.SmsSender.send_sms", fake)
        async with async_session_factory() as db:
            camp = await camp_svc.create_campaign(
                db, business_id=biz.id, segment="dormants", message="Bonjour {prenom} !!"
            )
            await db.commit()
            res = await camp_svc.deliver_campaign(db, camp.id)
        assert res["sent"] == 1 and sent == ["+33600000002"]
        async with async_session_factory() as db:
            assert (await db.get(Campaign, camp.id)).status == "sent"


# ── campagne figée ──


class TestCampagneFigee:
    async def test_echec_marque_failed(self, db_tables, monkeypatch) -> None:
        biz = await _biz()
        async with async_session_factory() as db:
            camp = await camp_svc.create_campaign(
                db, business_id=biz.id, segment="dormants", message="Bonjour {prenom} !!"
            )
            await db.commit()

        async def boom(db, cid, **kw):
            raise RuntimeError("base coupée")

        monkeypatch.setattr(camp_svc, "deliver_campaign", boom)
        await camp_svc.deliver_campaign_job(camp.id)
        async with async_session_factory() as db:
            assert (await db.get(Campaign, camp.id)).status == "failed"

    async def test_reprise_apres_redemarrage(self, db_tables, sms, no_redis) -> None:
        biz = await _biz()
        await _dormante(biz, "Anna")
        now = _now()
        async with async_session_factory() as s, s.begin():
            stale = Campaign(
                business_id=biz.id,
                segment="dormants",
                message="Bonjour {prenom}, on vous attend",
                status="sending",
                created_at=now - timedelta(minutes=30),
            )
            fresh = Campaign(
                business_id=biz.id,
                segment="nouveaux",
                message="Bonjour {prenom}, revenez vite",
                status="sending",
                created_at=now - timedelta(minutes=2),
            )
            old = Campaign(
                business_id=biz.id,
                segment="fideles",
                message="Bonjour {prenom}, merci à vous",
                status="sending",
                created_at=now - timedelta(days=3),
            )
            s.add_all([stale, fresh, old])
        assert await camp_svc.resume_stale_campaigns(now) == 1
        assert len(sms) == 1
        async with async_session_factory() as db:
            assert (await db.get(Campaign, stale.id)).status == "sent"
            # en cours : on attend
            assert (await db.get(Campaign, fresh.id)).status == "sending"
            assert (await db.get(Campaign, old.id)).status == "failed"
        # rejouée : pas de doublon
        async with async_session_factory() as s, s.begin():
            (await s.get(Campaign, stale.id)).status = "sending"
        await camp_svc.resume_stale_campaigns(now)
        assert len(sms) == 1


# ── STOP ──


class TestStop:
    async def test_idempotent_et_par_salon(self, db_tables) -> None:
        from jenny.services.offer_cap import apply_stop_reply

        biz, other = await _biz(), await _biz("Autre")
        c = await _cust(biz, "Alice")
        async with async_session_factory() as db:
            kw = {"business_id": biz.id, "customer_id": c.id}
            assert not await apply_stop_reply(db, text="stop je voulais dire jeudi", **kw)
            assert not await apply_stop_reply(
                db, business_id=other.id, customer_id=c.id, text="STOP"
            )
            assert await apply_stop_reply(db, text="Stop.", **kw)
            await db.commit()
        async with async_session_factory() as db:
            first = (await db.get(Customer, c.id)).marketing_opt_out_at
            assert first is not None
            assert await apply_stop_reply(db, text="stop svp", **kw)
            await db.commit()
        async with async_session_factory() as db:
            assert (await db.get(Customer, c.id)).marketing_opt_out_at == first

    async def test_via_conversation(self, db_tables) -> None:
        from jenny.services.offer_cap import apply_stop_reply

        biz = await _biz()
        c = await _cust(biz, "Alice")
        conv, anon = uuid4(), uuid4()
        async with async_session_factory() as s, s.begin():
            s.add(Conversation(id=conv, business_id=biz.id, customer_id=c.id, channel="whatsapp"))
            s.add(Conversation(id=anon, business_id=biz.id, channel="whatsapp"))
            s.add(WaitlistEntry(business_id=biz.id, conversation_id=anon, customer_name="Léa"))
        async with async_session_factory() as db:
            assert await apply_stop_reply(
                db, business_id=biz.id, customer_id=None, conversation_id=conv, text="STOP"
            )
            # anonyme : file vidée
            assert await apply_stop_reply(
                db, business_id=biz.id, customer_id=None, conversation_id=anon, text="arrêt"
            )
            assert not await apply_stop_reply(db, business_id=biz.id, customer_id=None, text="STOP")
            await db.commit()
        async with async_session_factory() as db:
            assert (await db.get(Customer, c.id)).marketing_opt_out_at is not None
            entry = (await db.execute(select(WaitlistEntry))).scalar_one()
        assert entry.status == "cancelled"

    async def test_aucun_message_commercial_apres_stop(self, db_tables, sms) -> None:
        from jenny.services.offer_cap import apply_stop_reply

        biz = await _biz()
        async with async_session_factory() as s, s.begin():
            s.add(Prestation(business_id=biz.id, name="Coupe", duration_minutes=30))
        alice = await _dormante(biz, "Alice")
        # relance due + attente
        rita = await _cust(biz, "Rita", phone="+33600000009")
        await _appt(biz, rita, _now() - timedelta(days=50))
        async with async_session_factory() as s, s.begin():
            s.add(WaitlistEntry(business_id=biz.id, customer_id=alice.id, service="Coupe"))
        async with async_session_factory() as db:
            for cid in (alice.id, rita.id):
                assert await apply_stop_reply(db, business_id=biz.id, customer_id=cid, text="STOP")
            await db.commit()
        async with async_session_factory() as db:
            camp = await camp_svc.create_campaign(
                db, business_id=biz.id, segment="dormants", message="Bonjour {prenom} !!"
            )
            await db.commit()
            assert (await camp_svc.deliver_campaign(db, camp.id))["sent"] == 0
            b = await db.get(Business, biz.id)
            rep = await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        assert rep.candidates == 0 and not sms

    async def test_attente_liee_a_une_fiche_stop(self, db_tables, monkeypatch) -> None:
        sent: list[str] = []

        async def fake_reply(channel, ext, text, **kw):
            sent.append(text)
            return True

        monkeypatch.setattr("jenny.connectors.reply_dispatch.send_channel_reply", fake_reply)
        biz = await _biz()
        c = await _cust(biz, "Alice", marketing_opt_out_at=_now())
        conv = uuid4()
        async with async_session_factory() as s, s.begin():
            s.add(
                Conversation(
                    id=conv,
                    business_id=biz.id,
                    customer_id=c.id,
                    channel="whatsapp",
                    external_conversation_id="wa:1",
                )
            )
            s.add(WaitlistEntry(business_id=biz.id, conversation_id=conv, customer_name="Al"))
        async with async_session_factory() as db:
            b = await db.get(Business, biz.id)
            rep = await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        assert rep.candidates == 0 and not sent


# ── liste d'attente ──


async def _attente(biz, name: str = "Wendy", service: str | None = None) -> Customer:
    w = await _cust(biz, name, phone="+33611111111")
    async with async_session_factory() as s, s.begin():
        s.add(WaitlistEntry(business_id=biz.id, customer_id=w.id, service=service))
    return w


class TestAttente:
    async def test_pas_de_nom_dune_autre_cliente(self, db_tables, sms, no_redis) -> None:
        from jenny.actions.handlers.manage_appointment import ManageAppointmentAction

        biz = await _biz()
        sophie = await _cust(biz, "Sophie Martin", phone="+33622222222")
        await _appt(
            biz,
            sophie,
            _now() + timedelta(hours=30),
            status="scheduled",
            title="RDV — Sophie Martin",
        )
        await _attente(biz)
        res = await ManageAppointmentAction().execute(
            {"business_id": str(biz.id), "customer_id": str(sophie.id), "operation": "cancel"}
        )
        assert res["success"]
        assert len(sms) == 1
        to, text = sms[0]
        assert to == "+33611111111"
        assert "Sophie" not in text and "Martin" not in text and "RDV —" not in text
        assert "assistante virtuelle" in text and "Salon Zoé" in text
        async with async_session_factory() as db:
            n = (await db.execute(select(Notification))).scalar_one()
        # le gérant, lui, voit tout
        assert "Wendy" in n.body

    async def test_prestation_du_catalogue(self, db_tables, sms, no_redis) -> None:
        from jenny.actions.handlers.manage_appointment import ManageAppointmentAction

        biz = await _biz()
        async with async_session_factory() as s, s.begin():
            s.add(Prestation(business_id=biz.id, name="Balayage", duration_minutes=90))
        sophie = await _cust(biz, "Sophie", phone="+33622222222")
        await _appt(
            biz,
            sophie,
            _now() + timedelta(hours=30),
            status="scheduled",
            minutes=90,
            title="Balayage Sophie (acompte en retard)",
        )
        await _attente(biz)
        await ManageAppointmentAction().execute(
            {"business_id": str(biz.id), "customer_id": str(sophie.id), "operation": "cancel"}
        )
        text = sms[0][1]
        assert "« Balayage »" in text and "acompte" not in text

    async def test_offre_tracee_et_tenue(self, db_tables, sms, no_redis) -> None:
        from jenny.actions.handlers.manage_appointment import ManageAppointmentAction

        biz = await _biz()
        sophie = await _cust(biz, "Sophie", phone="+33622222222")
        start = (_now() + timedelta(hours=30)).replace(second=0, microsecond=0)
        await _appt(biz, sophie, start, status="scheduled", minutes=45)
        wendy = await _attente(biz, service="Coupe")
        await ManageAppointmentAction().execute(
            {"business_id": str(biz.id), "customer_id": str(sophie.id), "operation": "cancel"}
        )
        async with async_session_factory() as db:
            offer = (await db.execute(select(SlotOffer))).scalar_one()
            assert offer.source == "waitlist" and offer.customer_id == wendy.id
            assert _aware(offer.slot_start) == start and offer.duration_minutes == 45
            assert offer.channel == "sms" and offer.sent_at is not None
            held, offered = await gap_filler._held_and_offered(db, biz.id, _now())
        assert (start, start + timedelta(minutes=45)) in held
        assert (str(wendy.id), start) in offered
        # une autre cliente : pas ce créneau
        tz = ZoneInfo("Europe/Paris")
        other = gap_filler.Candidate(
            source="rebook", duration=30, customer=SimpleNamespace(id=uuid4())
        )
        plan = gap_filler.plan_offers(
            [other], {30: [start]}, held=held, offered=offered, tz=tz, today=_now().date()
        )
        assert plan == []

    async def test_meme_creneau_pas_deux_fois(self, db_tables, sms) -> None:
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        biz = await _biz()
        await _attente(biz, service="Coupe")
        slot = _now() + timedelta(days=1)
        for _ in range(2):
            async with async_session_factory() as db:
                hit = await notify_waitlist_for_freed_slot(
                    db, business_id=biz.id, service="Coupe", slot_start=slot, duration_minutes=30
                )
                assert hit is not None
                hit.status = "waiting"  # on rejoue
                await db.commit()
        assert len(sms) == 1
        async with async_session_factory() as db:
            assert len((await db.execute(select(SlotOffer))).scalars().all()) == 1
            notes = (await db.execute(select(Notification))).scalars().all()
        assert any("déjà été proposé" in n.body for n in notes)

    async def test_annulation_gerant_tracee(self, db_tables, sms, no_redis) -> None:
        from jenny.services.owner_assistant import handle_owner_message

        biz = await _biz()
        marie = await _cust(biz, "Marie", phone="+33622222222")
        start = (_now() + timedelta(hours=30)).replace(second=0, microsecond=0)
        await _appt(biz, marie, start, status="scheduled")
        await _attente(biz, service="Coupe")
        async with async_session_factory() as db:
            out = await handle_owner_message(
                db, business_id=biz.id, actor="boss@x.com", message="annule le rdv de Marie"
            )
        assert out["data"].get("waitlist_notified") is True
        async with async_session_factory() as db:
            offer = (await db.execute(select(SlotOffer))).scalar_one()
        assert _aware(offer.slot_start) == start

    async def test_deplacement_trace_lancien_creneau(self, db_tables, sms, no_redis) -> None:
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        biz = await _biz()
        sophie = await _cust(biz, "Sophie", phone="+33622222222")
        old = (_now() + timedelta(hours=30)).replace(second=0, microsecond=0)
        a = await _appt(biz, sophie, old, status="scheduled", minutes=60)
        await _attente(biz)
        async with async_session_factory() as db:
            appt = await db.get(Appointment, a.id)
            appt.start_at = old + timedelta(days=1)
            appt.end_at = appt.start_at + timedelta(minutes=60)
            # un flush avant le crochet
            await db.flush()
            await notify_waitlist_for_freed_slot(db, business_id=biz.id, service=appt.title)
            await db.commit()
        async with async_session_factory() as db:
            offer = (await db.execute(select(SlotOffer))).scalar_one()
        assert _aware(offer.slot_start) == old and offer.duration_minutes == 60


# ── passe après changement (contrat staff) ──


class TestApresChangement:
    async def test_suppression_lance_une_passe(self, db_tables, sms, no_redis) -> None:
        biz = await _biz()
        rita = await _cust(biz, "Rita")
        await _appt(biz, rita, _now() - timedelta(days=50))
        a = await _appt(biz, None, _now() + timedelta(hours=5), status="scheduled")
        async with async_session_factory() as db:
            appt = await db.get(Appointment, a.id)
            await db.delete(appt)
            assert await gap_filler.schedule_after_change(db, biz.id, delay=0.05)
            assert biz.id not in gap_filler._pending  # attend le commit
            await db.commit()
            task = gap_filler._pending[biz.id]
        await asyncio.wait_for(task, timeout=30)
        async with async_session_factory() as db:
            offer = (await db.execute(select(SlotOffer))).scalar_one()
        assert offer.reason == "annulation" and offer.customer_id == rita.id
        assert len(sms) == 1

    async def test_deja_commite(self, db_tables, no_redis, monkeypatch) -> None:
        runs: list = []

        async def fake_run(bid, **kw):
            runs.append(bid)

        monkeypatch.setattr(gap_filler, "run_for_business", fake_run)
        bid = uuid4()
        async with async_session_factory() as db:
            assert await gap_filler.schedule_after_change(db, bid, delay=0)
            task = gap_filler._pending[bid]
        await asyncio.wait_for(task, timeout=5)
        assert runs == [bid]

    async def test_jamais_deux_passes_ensemble(self, db_tables, monkeypatch) -> None:
        biz = await _biz()
        inside = 0
        peak = 0

        async def slow(db, b, **kw):
            nonlocal inside, peak
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.05)
            inside -= 1
            return gap_filler.GapReport(business_id=b.id, reason="x")

        monkeypatch.setattr(gap_filler, "fill_gaps_for_business", slow)
        await asyncio.gather(*(gap_filler.run_for_business(biz.id) for _ in range(4)))
        assert peak == 1


# ── boucle de fond ──


class TestBoucle:
    async def test_tick_sans_worker(self, db_tables, sms, no_redis) -> None:
        biz = await _biz()
        rita = await _cust(biz, "Rita")
        await _appt(biz, rita, _now() - timedelta(days=50))
        morning = datetime.now(ZoneInfo("Europe/Paris")).replace(hour=9, minute=30)
        stats = await relances_loop.relances_tick(morning)
        assert stats["runs"] == 1 and stats["sent"] == 1 and stats["resumed"] == 0

    async def test_tick_laisse_le_worker(self, db_tables, monkeypatch) -> None:
        async def alive() -> bool:
            return True

        async def interdit(*a, **kw):
            raise AssertionError("le worker s'en charge")

        monkeypatch.setattr(gap_filler, "worker_alive", alive)
        monkeypatch.setattr(gap_filler, "run_gap_filler", interdit)
        assert await relances_loop.relances_tick() == {"skipped": "worker"}

    async def test_pas_deux_ticks(self, db_tables, monkeypatch) -> None:
        async def slow(now=None):
            await asyncio.sleep(0.1)
            return {"businesses": 0, "runs": 0, "sent": 0, "failed": 0}

        monkeypatch.setattr(gap_filler, "run_gap_filler", slow)
        a, b = await asyncio.gather(relances_loop.relances_tick(), relances_loop.relances_tick())
        assert {"skipped": "busy"} in (a, b)

    async def test_demarrage_arret(self, monkeypatch) -> None:
        monkeypatch.delenv("JENNY_RELANCES_LOOP", raising=False)
        prod = SimpleNamespace(env="prod")
        task = relances_loop.start_relances_loop(prod)
        assert task is not None and not task.done()
        # une seule boucle
        assert relances_loop.start_relances_loop(prod) is task
        await relances_loop.stop_relances_loop(task)
        assert task.cancelled()
        assert relances_loop.start_relances_loop(SimpleNamespace(env="test")) is None

    async def test_worker_alive_redis_mort(self, monkeypatch) -> None:
        from jenny.core.config import get_settings

        monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/15")
        gap_filler._worker_seen.clear()
        assert await gap_filler.worker_alive() is False

    async def test_lifespan_et_prechauffage(self, monkeypatch) -> None:
        import threading

        from jenny.api import main

        seen: list[str] = []

        class Emb:
            async def embed_text(self, text):
                return [0.0]

        monkeypatch.setattr("jenny.rag.embeddings.get_default_embedder", lambda: Emb())
        monkeypatch.setattr(
            "jenny.engine.factory.get_engine", lambda: seen.append(threading.current_thread().name)
        )
        await main._warmup_models()
        assert seen and seen[0] != threading.main_thread().name
        app = create_app()
        async with app.router.lifespan_context(app):
            # env=test : pas de boucle
            assert app.state.relances_task is None
            await app.state.warmup_task


# ── routes désinscription ──


class TestRoutesOptOut:
    async def test_lecture_liste_bascule(self, db_tables, client) -> None:
        biz, other = await _biz(), await _biz("Autre")
        alice = await _dormante(biz, "Alice")
        hana = await _cust(other, "Hana")
        h = _auth(biz)
        r = await client.get(f"/api/v1/campaigns/opt-out/{alice.id}", headers=h)
        assert r.status_code == 200 and r.json()["opt_out"] is False
        r = await client.put(
            f"/api/v1/campaigns/opt-out/{alice.id}", json={"opt_out": True}, headers=h
        )
        first = r.json()["opt_out_at"]
        assert r.json()["opt_out"] is True and first
        # recoché : date gardée
        r = await client.put(
            f"/api/v1/campaigns/opt-out/{alice.id}", json={"opt_out": True}, headers=h
        )
        assert r.json()["opt_out_at"] == first
        lst = (await client.get("/api/v1/campaigns/opt-outs", headers=h)).json()
        assert lst["total"] == 1 and lst["customers"][0]["name"] == "Alice"
        prev = (await client.get("/api/v1/campaigns/segments/dormants", headers=h)).json()
        row = next(s for s in prev["sample"] if s["id"] == str(alice.id))
        assert row["opt_out"] is True and row["eligible"] is False
        # autre salon : 404
        r = await client.get(f"/api/v1/campaigns/opt-out/{hana.id}", headers=h)
        assert r.status_code == 404
        assert (await client.get("/api/v1/campaigns/opt-outs", headers=_auth(other))).json()[
            "total"
        ] == 0
        r = await client.put(
            f"/api/v1/campaigns/opt-out/{alice.id}", json={"opt_out": False}, headers=h
        )
        assert r.json()["opt_out"] is False and r.json()["opt_out_at"] is None

    async def test_relance_passe_avec_texte_catalogue(self, db_tables, client, sms) -> None:
        biz = await _biz()
        async with async_session_factory() as s, s.begin():
            s.add(Prestation(business_id=biz.id, name="Coloration", duration_minutes=60))
        rita = await _cust(biz, "Rita")
        await _appt(
            biz, rita, _now() - timedelta(days=50), minutes=60, title="Coloration Rita note"
        )
        r = await client.post("/api/v1/campaigns/gaps/run", headers=_auth(biz))
        assert r.status_code == 200 and r.json()["sent"] == 1
        text = sms[0][1]
        assert "(Coloration)" in text and "note" not in text
