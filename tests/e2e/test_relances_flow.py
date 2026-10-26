"""Relances de bout en bout, sur SQLite réel.

Plafond anti-spam, segments, attribution, envoi de campagne,
remplissage des trous d'agenda (idempotent), routes cloisonnées.
Seul l'envoi SMS est simulé (pas de réseau).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import Campaign, CampaignRecipient, SlotOffer
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services import gap_filler

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
    """SMS simulé : tout part, on garde le texte."""
    sent: list[tuple[str, str]] = []

    async def fake(self, to, body):
        sent.append((to, body))
        return SimpleNamespace(success=True)

    monkeypatch.setattr("jenny.notifications.sms_sender.SmsSender.send_sms", fake)
    return sent


@pytest.fixture
def sms_ko(monkeypatch) -> list[str]:
    """SMS simulé en panne."""
    tries: list[str] = []

    async def fake(self, to, body):
        tries.append(to)
        return SimpleNamespace(success=False)

    monkeypatch.setattr("jenny.notifications.sms_sender.SmsSender.send_sms", fake)
    return tries


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


async def _cust(biz: Business, name: str, *, phone: str | None = "+33600000000", **kw) -> Customer:
    async with async_session_factory() as s, s.begin():
        c = Customer(id=uuid4(), business_id=biz.id, full_name=name, phone=phone, **kw)
        s.add(c)
    return c


async def _appt(
    biz: Business,
    cust: Customer | None,
    start: datetime,
    *,
    status: str = "completed",
    minutes: int = 30,
    title: str = "Coupe",
    created_at: datetime | None = None,
) -> Appointment:
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
        if created_at is not None:
            a.created_at = created_at
            a.updated_at = created_at
        s.add(a)
    return a


async def _visits(biz, cust, days_ago: list[int], **kw) -> None:
    for d in days_ago:
        await _appt(biz, cust, _now() - timedelta(days=d), **kw)


def _auth(biz: Business | None) -> dict[str, str]:
    token = create_access_token(uuid4(), "gerant@test.fr", [biz.id] if biz else [])
    return {"Authorization": f"Bearer {token}"}


# ── plafond anti-spam ──


class TestPlafond:
    async def test_claim_atomique_puis_rendu(self, db_tables) -> None:
        from jenny.services.offer_cap import can_offer, claim_offer, release_offer

        biz = await _biz()
        c = await _cust(biz, "Alice")
        async with async_session_factory() as db:
            cust = await db.get(Customer, c.id)
            claim = await claim_offer(db, cust)
            assert claim is not None
            assert await claim_offer(db, cust) is None  # 1 par semaine
            await release_offer(db, claim, cust)
            assert can_offer(cust)
            await db.commit()
        async with async_session_factory() as db:
            fresh = await db.get(Customer, c.id)
            assert fresh.offer_window_count == 0 and fresh.last_offer_at is None

    async def test_offre_plafonnee_mais_rappel_passe(self, db_tables, sms) -> None:
        from jenny.notifications.outbound import notify_customer

        biz = await _biz()
        c = await _cust(biz, "Alice")
        async with async_session_factory() as db:
            kw = {"business_id": biz.id, "customer_id": c.id, "text": "offre"}
            assert await notify_customer(db, commercial=True, **kw) == "sms"
            assert await notify_customer(db, commercial=True, **kw) is None
            # un rappel de RDV n'est pas plafonné
            assert await notify_customer(db, **kw) == "sms"
            await db.commit()
        assert len(sms) == 2
        async with async_session_factory() as db:
            fresh = await db.get(Customer, c.id)
            assert fresh.offer_window_count == 1 and fresh.last_offer_at is not None

    async def test_envoi_rate_ne_consomme_pas(self, db_tables, sms_ko) -> None:
        from jenny.notifications.outbound import notify_customer
        from jenny.services.offer_cap import can_offer

        biz = await _biz()
        c = await _cust(biz, "Alice")
        async with async_session_factory() as db:
            out = await notify_customer(
                db, business_id=biz.id, customer_id=c.id, text="offre", commercial=True
            )
            assert out is None and sms_ko
            assert can_offer(await db.get(Customer, c.id))

    async def test_stop_bloque_les_offres(self, db_tables, sms) -> None:
        from jenny.notifications.outbound import notify_customer
        from jenny.services.offer_cap import apply_stop_reply

        biz = await _biz()
        c = await _cust(biz, "Alice")
        async with async_session_factory() as db:
            assert await apply_stop_reply(db, business_id=biz.id, customer_id=c.id, text="STOP")
            # autre salon : rien
            assert not await apply_stop_reply(
                db, business_id=uuid4(), customer_id=c.id, text="STOP"
            )
            kw = {"business_id": biz.id, "customer_id": c.id, "text": "x"}
            assert await notify_customer(db, commercial=True, **kw) is None
            assert await notify_customer(db, **kw) == "sms"

    async def test_offre_sur_le_fil_dun_autre_salon(self, db_tables, monkeypatch) -> None:
        from jenny.domain.models.conversation import Conversation
        from jenny.notifications.outbound import notify_customer

        calls: list[str] = []

        async def fake_reply(channel, ext, text, **kw):
            calls.append(text)
            return True

        monkeypatch.setattr("jenny.connectors.reply_dispatch.send_channel_reply", fake_reply)
        mine, other = await _biz(), await _biz("Autre")
        conv = uuid4()
        async with async_session_factory() as s, s.begin():
            s.add(
                Conversation(
                    id=conv,
                    business_id=other.id,
                    channel="whatsapp",
                    external_conversation_id="wa:1",
                )
            )
        async with async_session_factory() as db:
            out = await notify_customer(
                db, business_id=mine.id, conversation_id=conv, text="offre", commercial=True
            )
        assert out is None and not calls


# ── segments ──


async def _seed_segments():
    biz = await _biz()
    other = await _biz("Autre salon")
    now = _now()
    people = {}
    people["alice"] = await _cust(biz, "Alice Martin")
    await _visits(biz, people["alice"], [300, 200, 120])
    people["bea"] = await _cust(biz, "Bea")
    await _visits(biz, people["bea"], [120])
    await _appt(biz, people["bea"], now + timedelta(days=3), status="scheduled")
    people["chloe"] = await _cust(biz, "Chloé")
    await _visits(biz, people["chloe"], [10])
    await _visits(biz, people["chloe"], [40, 60], status="no_show")
    people["dina"] = await _cust(biz, "Dina")
    await _visits(biz, people["dina"], [45])
    people["emma"] = await _cust(biz, "Emma")
    await _visits(biz, people["emma"], [10])
    people["fanny"] = await _cust(biz, "Fanny")
    await _visits(biz, people["fanny"], [5 + 20 * i for i in range(10)])
    people["gina"] = await _cust(biz, "Gina", anonymized_at=now)
    await _visits(biz, people["gina"], [150])
    people["iris"] = await _cust(biz, "Iris", phone=None)
    await _visits(biz, people["iris"], [100, 150])
    people["jade"] = await _cust(
        biz, "Jade", offer_window_start=now - timedelta(days=1), offer_window_count=1
    )
    await _visits(biz, people["jade"], [95, 160])
    people["kim"] = await _cust(biz, "Kim", marketing_opt_out_at=now)
    await _visits(biz, people["kim"], [130, 200])
    people["hana"] = await _cust(other, "Hana")
    await _visits(other, people["hana"], [200])
    # annulé : pas une visite
    people["lou"] = await _cust(biz, "Lou")
    await _appt(biz, people["lou"], now - timedelta(days=100), status="cancelled")
    return biz, other, people


class TestSegments:
    async def _names(self, biz, key) -> set[str]:
        from jenny.services.campaigns import segment_members

        async with async_session_factory() as db:
            return {m.customer.full_name for m in await segment_members(db, biz.id, key)}

    async def test_regles(self, db_tables) -> None:
        biz, _other, _p = await _seed_segments()
        assert await self._names(biz, "dormants") == {"Alice Martin", "Iris", "Jade", "Kim"}
        assert await self._names(biz, "no_shows") == {"Chloé"}
        assert await self._names(biz, "nouveaux") == {"Dina"}
        assert await self._names(biz, "fideles") == {"Fanny"}

    async def test_effectifs(self, db_tables) -> None:
        from jenny.services.campaigns import segment_counts

        biz, other, _p = await _seed_segments()
        async with async_session_factory() as db:
            c = await segment_counts(db, biz.id, "dormants")
            # Iris sans contact, Kim STOP, Jade plafonnée
            assert c == {"count": 4, "reachable": 2, "eligible": 1}
            assert (await segment_counts(db, other.id, "dormants"))["count"] == 1


# ── attribution ──


class TestAttribution:
    async def test_dernier_message_gagne_et_fenetre_30j(self, db_tables) -> None:
        from jenny.services.campaigns import campaign_history

        biz = await _biz()
        now = _now()
        alice, bea, dina, emma, fanny, zoe, hugo = [
            await _cust(biz, n) for n in ("Alice", "Bea", "Dina", "Emma", "Fanny", "Zoé", "Hugo")
        ]
        async with async_session_factory() as s, s.begin():
            s.add(Prestation(business_id=biz.id, name="Coupe", price_cents=3500))
            c1 = Campaign(
                business_id=biz.id,
                segment="dormants",
                message="m1",
                status="sent",
                sent_count=3,
                target_count=3,
                created_at=now - timedelta(days=40),
            )
            c2 = Campaign(
                business_id=biz.id,
                segment="nouveaux",
                message="m2",
                status="sent",
                sent_count=3,
                target_count=3,
                created_at=now - timedelta(days=10),
            )
            s.add_all([c1, c2])
            await s.flush()
            for cust in (alice, bea, emma):
                s.add(
                    CampaignRecipient(
                        campaign_id=c1.id,
                        customer_id=cust.id,
                        sent_at=now - timedelta(days=40),
                        channel="sms",
                    )
                )
            for cust in (alice, dina, fanny, hugo):
                s.add(
                    CampaignRecipient(
                        campaign_id=c2.id,
                        customer_id=cust.id,
                        sent_at=now - timedelta(days=10),
                        channel="sms",
                    )
                )
            # message raté : jamais attribué
            s.add(
                CampaignRecipient(
                    campaign_id=c2.id,
                    customer_id=zoe.id,
                    sent_at=now - timedelta(days=10),
                    channel=None,
                )
            )
        future = now + timedelta(days=5)
        await _appt(biz, alice, future, created_at=now - timedelta(days=5))  # c2
        await _appt(biz, bea, future, created_at=now - timedelta(days=35))  # c1
        await _appt(biz, dina, future, created_at=now - timedelta(days=12))  # avant envoi
        await _appt(biz, emma, future, created_at=now - timedelta(days=5))  # > 30 j
        await _appt(biz, fanny, future, status="cancelled", created_at=now - timedelta(days=3))
        await _appt(biz, zoe, future, created_at=now - timedelta(days=3))
        # visite ancienne saisie après coup (import)
        await _appt(biz, hugo, now - timedelta(days=60), created_at=now - timedelta(days=3))

        async with async_session_factory() as db:
            items = {i["message"]: i for i in await campaign_history(db, biz.id)}
        assert items["m1"]["returned_count"] == 1  # Bea
        assert items["m2"]["returned_count"] == 1  # Alice
        assert items["m2"]["revenue_eur"] == 35.0
        assert items["m1"]["window_open"] is False and items["m2"]["window_open"] is True


# ── envoi de campagne ──


class TestDeliver:
    async def test_envoi_plafonne_et_rejouable(self, db_tables, sms) -> None:
        from jenny.services.campaigns import create_campaign, deliver_campaign

        biz, _o, p = await _seed_segments()
        async with async_session_factory() as db:
            camp = await create_campaign(
                db, business_id=biz.id, segment="dormants", message="Coucou {prenom}, ça va ?"
            )
            await db.commit()
            res = await deliver_campaign(db, camp.id)
            assert res == {"sent": 1, "skipped": 3}
            again = await deliver_campaign(db, camp.id)
            assert again["sent"] == 1
        assert len(sms) == 1  # Alice seulement, une fois
        assert sms[0][1].startswith("Coucou Alice, ça va ?") and "STOP" in sms[0][1]
        async with async_session_factory() as db:
            rows = (await db.execute(select(CampaignRecipient))).scalars().all()
            assert [(r.customer_id, r.channel) for r in rows] == [(p["alice"].id, "sms")]
            assert (await db.get(Campaign, camp.id)).status == "sent"

    async def test_validation(self, db_tables) -> None:
        from jenny.services.campaigns import CampaignError, create_campaign

        biz = await _biz()
        async with async_session_factory() as db:
            with pytest.raises(CampaignError):
                await create_campaign(db, business_id=biz.id, segment="zzz", message="x" * 20)
            with pytest.raises(CampaignError):
                await create_campaign(db, business_id=biz.id, segment="dormants", message="hey")


# ── trous d'agenda ──


async def _seed_gaps():
    biz = await _biz()
    now = _now()
    async with async_session_factory() as s, s.begin():
        s.add(Prestation(business_id=biz.id, name="Coupe", duration_minutes=30, price_cents=3000))
    wendy = await _cust(biz, "Wendy")
    async with async_session_factory() as s, s.begin():
        s.add(
            WaitlistEntry(
                business_id=biz.id,
                customer_id=wendy.id,
                service="Coupe",
                customer_name="Wendy",
                status="waiting",
            )
        )
    rita = await _cust(biz, "Rita")
    await _visits(biz, rita, [50], minutes=60, title="Couleur")
    nina = await _cust(biz, "Nina")
    await _visits(biz, nina, [5])
    ulla = await _cust(biz, "Ulla")
    await _visits(biz, ulla, [60])
    await _appt(biz, ulla, now + timedelta(days=6), status="scheduled")
    return biz, {"wendy": wendy, "rita": rita, "nina": nina, "ulla": ulla}


class TestGapFiller:
    async def test_liste_attente_puis_relance_due(self, db_tables, sms) -> None:
        biz, p = await _seed_gaps()
        async with async_session_factory() as db:
            b = await db.get(Business, biz.id)
            rep = await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        assert rep.sent == 2 and rep.failed == 0
        assert [x.candidate.source for x in rep.planned] == ["waitlist", "rebook"]
        first, second = rep.planned
        assert first.candidate.customer.id == p["wendy"].id
        assert second.candidate.customer.id == p["rita"].id
        assert second.candidate.duration == 60 and second.candidate.service == "Couleur"
        # pas de chevauchement
        assert second.slot_start >= first.slot_end or second.slot_end <= first.slot_start
        assert all("assistante virtuelle" in t and "/book/" in t for _to, t in sms)
        async with async_session_factory() as db:
            offers = (await db.execute(select(SlotOffer))).scalars().all()
            assert {o.channel for o in offers} == {"sms"} and len(offers) == 2
            entry = (await db.execute(select(WaitlistEntry))).scalar_one()
            assert entry.status == "notified"

    async def test_idempotent(self, db_tables, sms_ko) -> None:
        biz, _p = await _seed_gaps()
        for _ in range(3):
            async with async_session_factory() as db:
                b = await db.get(Business, biz.id)
                await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        async with async_session_factory() as db:
            offers = (await db.execute(select(SlotOffer))).scalars().all()
        keys = [(o.recipient_key, o.slot_start) for o in offers]
        # envois ratés : on réessaie, jamais le même créneau
        assert len(offers) == 6 and len(set(keys)) == 6

    async def test_plafond_respecte_au_2e_passage(self, db_tables, sms) -> None:
        biz, _p = await _seed_gaps()
        for _ in range(2):
            async with async_session_factory() as db:
                b = await db.get(Business, biz.id)
                await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        assert len(sms) == 2

    async def test_doublon_refuse_par_la_base(self, db_tables) -> None:
        biz = await _biz()
        slot = _now() + timedelta(days=1)
        kw = {"business_id": biz.id, "recipient_key": "k", "slot_start": slot, "source": "rebook"}
        async with async_session_factory() as db:
            db.add(SlotOffer(**kw))
            await db.commit()
            db.add(SlotOffer(**kw))
            with pytest.raises(IntegrityError):
                await db.commit()

    async def test_insert_once_sans_exception(self, db_tables) -> None:
        from jenny.services.campaigns import insert_once

        biz = await _biz()
        slot = _now() + timedelta(days=1)
        vals = {"business_id": biz.id, "recipient_key": "k", "slot_start": slot, "source": "rebook"}
        keys = ["business_id", "recipient_key", "slot_start"]
        async with async_session_factory() as db:
            assert await insert_once(db, SlotOffer, {"id": uuid4(), **vals}, keys)
            assert not await insert_once(db, SlotOffer, {"id": uuid4(), **vals}, keys)
            await db.commit()
            assert (await db.execute(select(func.count(SlotOffer.id)))).scalar_one() == 1

    async def test_attente_anonyme_whatsapp(self, db_tables, monkeypatch) -> None:
        from jenny.domain.models.conversation import Conversation

        sent: list[str] = []

        async def fake_reply(channel, ext, text, **kw):
            sent.append(text)
            return True

        monkeypatch.setattr("jenny.connectors.reply_dispatch.send_channel_reply", fake_reply)
        biz = await _biz()
        wa, web = uuid4(), uuid4()
        async with async_session_factory() as s, s.begin():
            s.add(
                Conversation(
                    id=wa,
                    business_id=biz.id,
                    channel="whatsapp",
                    external_conversation_id="wa:33600000000",
                )
            )
            s.add(Conversation(id=web, business_id=biz.id, channel="web"))
            s.add(WaitlistEntry(business_id=biz.id, conversation_id=web, customer_name="Web"))
            s.add(WaitlistEntry(business_id=biz.id, conversation_id=wa, customer_name="Léa"))
        async with async_session_factory() as db:
            b = await db.get(Business, biz.id)
            rep = await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        # le chat web anonyme n'est pas joignable
        assert rep.candidates == 1 and rep.sent == 1
        assert sent and sent[0].startswith("Bonjour Léa !")

    async def test_rien_la_nuit(self, db_tables, sms) -> None:
        biz, _p = await _seed_gaps()
        night = datetime.now(ZoneInfo("Europe/Paris")).replace(hour=23, minute=0)
        async with async_session_factory() as db:
            b = await db.get(Business, biz.id)
            rep = await gap_filler.fill_gaps_for_business(db, b, now=night, reason="matin")
        assert rep.skipped and rep.sent == 0 and not sms

    async def test_cron_passe_du_matin_une_fois(self, db_tables, sms) -> None:
        await _seed_gaps()
        morning = datetime.now(ZoneInfo("Europe/Paris")).replace(hour=9, minute=30)
        first = await gap_filler.run_gap_filler(now=morning)
        assert first["runs"] == 1 and first["sent"] == 2
        again = await gap_filler.run_gap_filler(now=morning + timedelta(minutes=10))
        assert again["runs"] == 0
        assert len(sms) == 2

    async def test_annulation_recente_detectee(self, db_tables) -> None:
        biz = await _biz()
        now = _now()
        async with async_session_factory() as db:
            assert not await gap_filler._recent_agenda_change(db, biz.id, now)
        await _appt(biz, None, now + timedelta(hours=5), status="cancelled", created_at=now)
        async with async_session_factory() as db:
            assert await gap_filler._recent_agenda_change(db, biz.id, now)

    async def test_stats_rempli(self, db_tables, sms) -> None:
        biz, p = await _seed_gaps()
        async with async_session_factory() as db:
            b = await db.get(Business, biz.id)
            await gap_filler.fill_gaps_for_business(db, b, reason="manuel")
        # Rita réserve juste après
        await _appt(
            biz,
            p["rita"],
            _now() + timedelta(days=1),
            status="scheduled",
            created_at=_now() + timedelta(minutes=5),
        )
        async with async_session_factory() as db:
            st = await gap_filler.offer_stats(db, biz.id)
        assert st == {"sent": 2, "failed": 0, "filled": 1}


# ── liste d'attente branchée ──


class TestWaitlistHook:
    async def test_client_plafonne_pas_de_message(self, db_tables, sms) -> None:
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        biz = await _biz()
        c = await _cust(
            biz, "Wendy", offer_window_start=_now() - timedelta(days=1), offer_window_count=1
        )
        async with async_session_factory() as s, s.begin():
            s.add(WaitlistEntry(business_id=biz.id, customer_id=c.id, service="Coupe"))
        async with async_session_factory() as db:
            hit = await notify_waitlist_for_freed_slot(db, business_id=biz.id, service="Coupe")
            await db.commit()
        assert hit is not None and not sms
        async with async_session_factory() as db:
            n = (await db.execute(select(Notification))).scalar_one()
        assert "Pas de message auto" in n.body

    async def test_sans_attente_lance_une_passe(self, db_tables, sms, monkeypatch) -> None:
        from jenny.core.config import get_settings
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        monkeypatch.setattr(get_settings(), "redis_url", "")
        monkeypatch.setattr(gap_filler, "in_send_hours", lambda b, n: True)
        biz = await _biz()
        rita = await _cust(biz, "Rita")
        await _visits(biz, rita, [50])
        async with async_session_factory() as db:
            assert await notify_waitlist_for_freed_slot(db, business_id=biz.id) is None
            await db.commit()
        task = gap_filler._pending.get(biz.id)
        assert task is not None
        await asyncio.wait_for(task, timeout=30)
        async with async_session_factory() as db:
            offer = (await db.execute(select(SlotOffer))).scalar_one()
        assert offer.reason == "annulation" and offer.customer_id == rita.id
        assert len(sms) == 1

    async def test_avec_redis_le_worker_sen_charge(self, db_tables) -> None:
        async with async_session_factory() as db:
            assert gap_filler.schedule_after_change(db, uuid4()) is False

    def test_cron_branche(self) -> None:
        from jenny.workers.tasks import WorkerSettings, fill_agenda_gaps

        assert fill_agenda_gaps in WorkerSettings.functions
        assert "cron:fill_agenda_gaps" in [c.name for c in WorkerSettings.cron_jobs]


# ── routes ──


class TestRoutes:
    async def test_isolation_salon(self, db_tables, client, sms) -> None:
        biz, other, p = await _seed_segments()
        r = await client.get("/api/v1/campaigns/segments", headers=_auth(biz))
        assert r.status_code == 200
        dormants = next(s for s in r.json() if s["key"] == "dormants")
        assert dormants["count"] == 4
        r = await client.get("/api/v1/campaigns/segments/dormants", headers=_auth(other))
        assert [s["name"] for s in r.json()["sample"]] == ["Hana"]
        # pas de salon : 403
        r = await client.get("/api/v1/campaigns/segments", headers=_auth(None))
        assert r.status_code == 403
        # client d'un autre salon : 404
        r = await client.put(
            f"/api/v1/campaigns/opt-out/{p['hana'].id}", json={"opt_out": True}, headers=_auth(biz)
        )
        assert r.status_code == 404
        r = await client.get("/api/v1/campaigns/segments")
        assert r.status_code == 401

    async def test_envoi_et_historique(self, db_tables, client, sms) -> None:
        biz, other, _p = await _seed_segments()
        body = {
            "segment": "dormants",
            "message": "Bonjour {prenom}, on vous attend !",
            "business_id": str(other.id),  # ignoré
        }
        r = await client.post("/api/v1/campaigns", json=body, headers=_auth(biz))
        assert r.status_code == 202, r.text
        assert r.json()["target_count"] == 4
        # double clic : refusé
        r2 = await client.post("/api/v1/campaigns", json=body, headers=_auth(biz))
        assert r2.status_code == 422
        h = (await client.get("/api/v1/campaigns", headers=_auth(biz))).json()
        assert len(h["campaigns"]) == 1 and h["campaigns"][0]["sent_count"] == 1
        assert h["summary"]["sent"] == 1
        assert (await client.get("/api/v1/campaigns", headers=_auth(other))).json()[
            "campaigns"
        ] == []
        async with async_session_factory() as db:
            camp = (await db.execute(select(Campaign))).scalar_one()
            assert camp.business_id == biz.id

    async def test_opt_out_et_rendu(self, db_tables, client) -> None:
        biz = await _biz()
        c = await _cust(biz, "Alice")
        r = await client.put(
            f"/api/v1/campaigns/opt-out/{c.id}", json={"opt_out": True}, headers=_auth(biz)
        )
        assert r.status_code == 200 and r.json()["opt_out"] is True
        r = await client.post(
            "/api/v1/campaigns/render",
            json={"message": "Coucou {prenom} !", "name": "léa"},
            headers=_auth(biz),
        )
        assert r.json()["text"].startswith("Coucou Léa !") and r.json()["sms_parts"] >= 1

    async def test_trous(self, db_tables, client, sms) -> None:
        biz, _p = await _seed_gaps()
        r = await client.get("/api/v1/campaigns/gaps", headers=_auth(biz))
        assert r.status_code == 200
        data = r.json()
        assert data["gaps"] and data["candidates"] == 2 and len(data["planned"]) == 2
        assert not sms  # aperçu : rien ne part
        r = await client.post("/api/v1/campaigns/gaps/run", headers=_auth(biz))
        assert r.json()["sent"] == 2
        async with async_session_factory() as db:
            n = (await db.execute(select(func.count(SlotOffer.id)))).scalar_one()
        assert n == 2
