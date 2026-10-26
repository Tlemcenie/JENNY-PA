"""Remplit les trous d'agenda d'aujourd'hui et de demain.

Chaque matin, puis après une annulation ou un déplacement, on cherche
les créneaux libres, on choisit qui prévenir (liste d'attente d'abord,
puis les clients dont la relance est due) et on leur propose la place.

Garde-fous : plafond anti-spam par client, jamais deux fois le même
créneau au même client, un créneau proposé reste « tenu » quelques
heures, et rien ne part la nuit. Chaque offre est enregistrée.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import lazyload

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import SlotOffer
from jenny.domain.models.customer import Customer
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services.availability import business_tz, free_slots_for_day
from jenny.services.campaigns import (
    NO_SHOW_MIN,
    NOT_BOOKING,
    direct_conversations,
    first_name,
    insert_once,
    is_reachable,
    visit_stats,
)
from jenny.services.offer_cap import can_offer

if TYPE_CHECKING:
    from uuid import UUID
    from zoneinfo import ZoneInfo

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# heures d'envoi (locales)
SEND_FROM = time(9, 0)
SEND_UNTIL = time(20, 0)
# passe du matin
MORNING_FROM = time(9, 0)
MORNING_UNTIL = time(11, 0)
# pas de créneau trop proche
LEAD = timedelta(hours=2)
# créneau tenu après une offre
SLOT_HOLD = timedelta(hours=3)
MAX_OFFERS_PER_RUN = 8
# relance due
REBOOK_MIN_DAYS = 21
REBOOK_MAX_DAYS = 180
DEFAULT_CYCLE_DAYS = 42
REBOOK_POOL = 40
# annulation récente
RECENT_CHANGE = timedelta(minutes=15)
# un RDV pris dans les 2 jours = rempli
FILLED_WINDOW = timedelta(days=2)

_DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _aware(dt: datetime | None) -> datetime | None:
    """Datetime naïve -> UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(slots=True)
class Candidate:
    """Quelqu'un à qui proposer une place."""

    source: str  # waitlist | rebook
    duration: int
    service: str | None = None
    customer: Customer | None = None
    conversation_id: UUID | None = None
    entry: WaitlistEntry | None = None
    name: str | None = None
    window: str | None = None
    score: float = 0.0

    @property
    def recipient_key(self) -> str:
        if self.customer is not None:
            return str(self.customer.id)
        return f"conv:{self.conversation_id}"


@dataclass(slots=True)
class PlannedOffer:
    candidate: Candidate
    slot_start: datetime

    @property
    def slot_end(self) -> datetime:
        return self.slot_start + timedelta(minutes=self.candidate.duration)


@dataclass(slots=True)
class GapReport:
    business_id: UUID
    reason: str
    gaps: list[datetime] = field(default_factory=list)
    candidates: int = 0
    planned: list[PlannedOffer] = field(default_factory=list)
    sent: int = 0
    failed: int = 0
    skipped: str | None = None


# ── fenêtre voulue (liste d'attente) ──


def window_ok(window: str | None, local: datetime, today: date) -> bool:
    """Le créneau colle à « mardi matin », « demain »… ?"""
    w = (window or "").lower()
    if not w:
        return True
    if "aujourd" in w and local.date() != today:
        return False
    if "demain" in w and local.date() != today + timedelta(days=1):
        return False
    h = local.hour + local.minute / 60
    if "matin" in w and h >= 12:
        return False
    if ("après-midi" in w or "apres-midi" in w or "aprem" in w) and not 12 <= h < 18:
        return False
    if "soir" in w and h < 17:
        return False
    # jour de semaine cité
    return all(not (d in w and local.weekday() != i) for i, d in enumerate(_DAYS_FR))


def when_label(slot: datetime, tz: ZoneInfo, now: datetime) -> str:
    """« aujourd'hui à 14h00 », « demain à 10h30 »."""
    loc = slot.astimezone(tz)
    today = now.astimezone(tz).date()
    hour = loc.strftime("%Hh%M")
    if loc.date() == today:
        return f"aujourd'hui à {hour}"
    if loc.date() == today + timedelta(days=1):
        return f"demain à {hour}"
    return f"{_DAYS_FR[loc.weekday()]} {loc.day:02d}/{loc.month:02d} à {hour}"


def offer_text(c: Candidate, *, salon: str, when: str, link: str | None) -> str:
    """Message envoyé au client."""
    prenom = first_name(c.name)
    hello = f"Bonjour {prenom} !" if prenom else "Bonjour !"
    # sans « » : SMS moins cher
    svc = f" ({c.service})" if c.service else ""
    if c.source == "waitlist":
        body = f"Bonne nouvelle : une place s'est libérée {when}{svc}, comme vous l'attendiez."
    else:
        body = f"Une place vient de se libérer {when}{svc}, on a pensé à vous."
    book = (
        f" Réservez-la ici : {link} ou répondez-moi." if link else " Répondez-moi pour la bloquer."
    )
    return (
        f"{hello} Ici Jenny, l'assistante virtuelle de {salon}. {body}{book} "
        "STOP pour ne plus recevoir d'offres."
    )


def booking_link(business: Business) -> str | None:
    """Lien de résa publique du salon."""
    from jenny.core.config import get_settings

    if not business.slug:
        return None
    base = (get_settings().app_base_url or "").rstrip("/")
    return f"{base}/book/{business.slug}" if base else None


# ── plan (pur, testable) ──


def plan_offers(
    candidates: list[Candidate],
    gaps: dict[int, list[datetime]],
    *,
    held: list[tuple[datetime, datetime]],
    offered: set[tuple[str, datetime]],
    tz: ZoneInfo,
    today: date,
    limit: int = MAX_OFFERS_PER_RUN,
) -> list[PlannedOffer]:
    """Une place par candidat, sans chevauchement."""
    plan: list[PlannedOffer] = []
    taken = list(held)
    seen: set[str] = set()
    for c in candidates:
        if len(plan) >= limit:
            break
        if c.recipient_key in seen:
            continue
        step = timedelta(minutes=c.duration)
        for s in gaps.get(c.duration, []):
            e = s + step
            if (c.recipient_key, s) in offered:
                continue
            if any(s < he and e > hs for hs, he in taken):
                continue
            if c.source == "waitlist" and not window_ok(c.window, s.astimezone(tz), today):
                continue
            plan.append(PlannedOffer(candidate=c, slot_start=s))
            taken.append((s, e))
            seen.add(c.recipient_key)
            break
    return plan


# ── lecture base ──


async def find_gaps(
    db: AsyncSession, business: Business, durations: set[int], now: datetime
) -> dict[int, list[datetime]]:
    """Créneaux libres aujourd'hui + demain, par durée."""
    tz = business_tz(business)
    today = now.astimezone(tz).date()
    earliest = now + LEAD
    out: dict[int, list[datetime]] = {}
    for d in sorted(durations):
        slots: list[datetime] = []
        for day in (today, today + timedelta(days=1)):
            for s in await free_slots_for_day(db, business.id, day, d, business=business):
                s = _aware(s)
                if s >= earliest:
                    slots.append(s)
        out[d] = sorted(slots)
    return out


def _duration_for(service: str | None, prestations: list) -> int:
    """Durée de la prestation, 30 min sinon."""
    from jenny.services.prestation_service import find_prestation

    p = find_prestation(prestations, service or "") if service and prestations else None
    return max(15, min(240, int(p.duration_minutes))) if p is not None else 30


async def waitlist_candidates(
    db: AsyncSession, business: Business, prestations: list, now: datetime
) -> list[Candidate]:
    """Inscrits en liste d'attente, plus anciens d'abord."""
    entries = (
        (
            await db.execute(
                select(WaitlistEntry)
                .where(WaitlistEntry.business_id == business.id, WaitlistEntry.status == "waiting")
                .order_by(WaitlistEntry.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    out: list[Candidate] = []
    for e in entries:
        cust = None
        conv_ok = await _direct_conv(db, business.id, e.conversation_id)
        if e.customer_id is not None:
            cust = await db.get(Customer, e.customer_id, options=[lazyload("*")])
            if cust is None or cust.business_id != business.id:
                continue
            if not can_offer(cust, now):
                continue
            convs = {cust.id: e.conversation_id} if conv_ok else {}
            if not is_reachable(cust, convs):
                continue
        elif not conv_ok:
            # anonyme sans canal direct
            continue
        out.append(
            Candidate(
                source="waitlist",
                duration=_duration_for(e.service, prestations),
                service=e.service,
                customer=cust,
                conversation_id=e.conversation_id,
                entry=e,
                name=(cust.full_name if cust else None) or e.customer_name,
                window=e.desired_window,
            )
        )
    return out


async def _direct_conv(db: AsyncSession, business_id: UUID, conv_id: UUID | None) -> bool:
    """Fil WhatsApp/Insta joignable ?"""
    from jenny.domain.models.conversation import Conversation
    from jenny.services.campaigns import DIRECT_CHANNELS

    if conv_id is None:
        return False
    conv = await db.get(Conversation, conv_id, options=[lazyload("*")])
    return (
        conv is not None
        and conv.business_id == business_id
        and conv.channel in DIRECT_CHANNELS
        and bool(conv.external_conversation_id)
    )


async def rebook_candidates(
    db: AsyncSession, business: Business, now: datetime, *, pool: int = REBOOK_POOL
) -> list[Candidate]:
    """Clients dont la relance est due, plus en retard d'abord."""
    vs = visit_stats(business.id, now)
    rows = (
        await db.execute(
            select(Customer, vs.c.visits, vs.c.first_visit, vs.c.last_visit)
            .join(vs, vs.c.customer_id == Customer.id)
            .where(
                Customer.business_id == business.id,
                Customer.anonymized_at.is_(None),
                Customer.marketing_opt_out_at.is_(None),
                vs.c.visits >= 1,
                vs.c.upcoming == 0,
                vs.c.no_shows < NO_SHOW_MIN,
                vs.c.last_visit <= now - timedelta(days=REBOOK_MIN_DAYS),
                vs.c.last_visit >= now - timedelta(days=REBOOK_MAX_DAYS),
            )
            .options(lazyload("*"))
        )
    ).all()

    scored: list[tuple[float, Customer]] = []
    for cust, visits, first, last in rows:
        last_dt, first_dt = _aware(_as_dt(last)), _aware(_as_dt(first))
        if last_dt is None or not can_offer(cust, now):
            continue
        cycle = DEFAULT_CYCLE_DAYS
        if visits and visits >= 2 and first_dt is not None:
            # rythme perso du client
            cycle = max(14, (last_dt - first_dt).days / (visits - 1))
        since = (now - last_dt).days
        if since < max(REBOOK_MIN_DAYS, 0.9 * cycle):
            continue
        scored.append((since / cycle, cust))
    scored.sort(key=lambda t: -t[0])
    scored = scored[:pool]
    if not scored:
        return []

    ids = [c.id for _s, c in scored]
    convs = await direct_conversations(db, business.id, ids)
    last_appt = await _last_visits(db, business.id, ids, now)
    out: list[Candidate] = []
    for score, cust in scored:
        if not is_reachable(cust, convs):
            continue
        appt = last_appt.get(cust.id)
        duration = 30
        if appt is not None:
            mins = int((_aware(appt.end_at) - _aware(appt.start_at)).total_seconds() // 60)
            duration = max(15, min(240, mins))
        out.append(
            Candidate(
                source="rebook",
                duration=duration,
                service=appt.title if appt is not None else None,
                customer=cust,
                conversation_id=convs.get(cust.id),
                name=cust.full_name,
                score=round(score, 2),
            )
        )
    return out


def _as_dt(v: Any) -> datetime | None:
    """Texte SQLite -> datetime."""
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


async def _last_visits(
    db: AsyncSession, business_id: UUID, ids: list[UUID], now: datetime
) -> dict[UUID, Appointment]:
    """Dernière visite de chaque client."""
    rows = (
        (
            await db.execute(
                select(Appointment)
                .where(
                    Appointment.business_id == business_id,
                    Appointment.customer_id.in_(ids),
                    Appointment.status.notin_(("cancelled", "blocked", "no_show")),
                    Appointment.start_at < now,
                )
                .order_by(Appointment.start_at.desc())
                .options(lazyload("*"))
            )
        )
        .scalars()
        .all()
    )
    out: dict[UUID, Appointment] = {}
    for a in rows:
        out.setdefault(a.customer_id, a)
    return out


async def _held_and_offered(
    db: AsyncSession, business_id: UUID, now: datetime
) -> tuple[list[tuple[datetime, datetime]], set[tuple[str, datetime]]]:
    """Créneaux tenus + déjà proposés."""
    rows = (
        (
            await db.execute(
                select(SlotOffer).where(
                    SlotOffer.business_id == business_id,
                    SlotOffer.slot_start >= now - timedelta(hours=1),
                )
            )
        )
        .scalars()
        .all()
    )
    held: list[tuple[datetime, datetime]] = []
    offered: set[tuple[str, datetime]] = set()
    for o in rows:
        start = _aware(o.slot_start)
        offered.add((o.recipient_key, start))
        sent = _aware(o.sent_at)
        if o.channel and sent is not None and now - sent < SLOT_HOLD:
            held.append((start, start + timedelta(minutes=o.duration_minutes)))
    return held, offered


def in_send_hours(business: Business, now: datetime) -> bool:
    """Pas de message la nuit."""
    loc = now.astimezone(business_tz(business)).time()
    return SEND_FROM <= loc < SEND_UNTIL


# ── le job ──


async def fill_gaps_for_business(
    db: AsyncSession,
    business: Business,
    *,
    now: datetime | None = None,
    reason: str = "matin",
    dry_run: bool = False,
    limit: int = MAX_OFFERS_PER_RUN,
) -> GapReport:
    """Cherche les trous et propose les places."""
    from jenny.services.prestation_service import load_active_prestations

    now = _aware(now) or datetime.now(UTC)
    report = GapReport(business_id=business.id, reason=reason)
    if not dry_run and reason != "manuel" and not in_send_hours(business, now):
        report.skipped = "hors des heures d'envoi"
        return report

    tz = business_tz(business)
    prestations = await load_active_prestations(db, business.id)
    candidates = await waitlist_candidates(db, business, prestations, now)
    candidates += await rebook_candidates(db, business, now)
    report.candidates = len(candidates)

    gaps = await find_gaps(db, business, {30} | {c.duration for c in candidates}, now)
    report.gaps = gaps.get(30, [])
    if not candidates or not any(gaps.values()):
        return report

    held, offered = await _held_and_offered(db, business.id, now)
    report.planned = plan_offers(
        candidates,
        gaps,
        held=held,
        offered=offered,
        tz=tz,
        today=now.astimezone(tz).date(),
        limit=limit,
    )
    if dry_run:
        return report

    salon = business.name or "votre salon"
    link = booking_link(business)
    for p in report.planned:
        ok = await _send_offer(db, business, p, reason=reason, salon=salon, link=link, now=now)
        if ok is True:
            report.sent += 1
        elif ok is False:
            report.failed += 1
    logger.info(
        "gap_filler.done",
        business_id=str(business.id),
        reason=reason,
        gaps=len(report.gaps),
        sent=report.sent,
        failed=report.failed,
    )
    return report


async def _send_offer(
    db: AsyncSession,
    business: Business,
    p: PlannedOffer,
    *,
    reason: str,
    salon: str,
    link: str | None,
    now: datetime,
) -> bool | None:
    """Trace l'offre, envoie, note le canal."""
    from jenny.notifications.outbound import notify_customer

    c = p.candidate
    offer_id = uuid4()
    customer_id = c.customer.id if c.customer is not None else None
    values = {
        "id": offer_id,
        "business_id": business.id,
        "customer_id": customer_id,
        "conversation_id": c.conversation_id,
        "waitlist_entry_id": c.entry.id if c.entry is not None else None,
        "recipient_key": c.recipient_key,
        "slot_start": p.slot_start,
        "duration_minutes": c.duration,
        "service": c.service[:120] if c.service else None,
        "source": c.source,
        "reason": reason,
    }
    # trace avant envoi : jamais 2 fois
    keys = ["business_id", "recipient_key", "slot_start"]
    if not await insert_once(db, SlotOffer, values, keys):
        return None
    await db.commit()

    tz = business_tz(business)
    text = offer_text(c, salon=salon, when=when_label(p.slot_start, tz, now), link=link)
    canal = await notify_customer(
        db,
        business_id=business.id,
        customer_id=customer_id,
        conversation_id=c.conversation_id,
        text=text,
        subject=f"Une place s'est libérée chez {salon}",
        commercial=True,
    )
    if canal:
        await db.execute(
            update(SlotOffer)
            .where(SlotOffer.id == offer_id)
            .values(channel=canal, sent_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        if c.entry is not None:
            c.entry.status = "notified"
            c.entry.notified_at = datetime.now(UTC)
    await db.commit()
    return bool(canal)


async def _recent_agenda_change(db: AsyncSession, business_id: UUID, now: datetime) -> bool:
    """Une annulation récente, sur aujourd'hui ou demain ?

    Les déplacements passent par le crochet liste d'attente.
    """
    row = (
        await db.execute(
            select(Appointment.id)
            .where(
                Appointment.business_id == business_id,
                Appointment.status == "cancelled",
                Appointment.updated_at >= now - RECENT_CHANGE,
                Appointment.start_at >= now,
                Appointment.start_at <= now + timedelta(days=2),
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def _morning_done(db: AsyncSession, business: Business, now: datetime) -> bool:
    """La passe du matin a déjà envoyé ?"""
    tz = business_tz(business)
    loc = now.astimezone(tz)
    midnight = datetime(loc.year, loc.month, loc.day, tzinfo=tz).astimezone(UTC)
    row = (
        await db.execute(
            select(SlotOffer.id)
            .where(
                SlotOffer.business_id == business.id,
                SlotOffer.reason == "matin",
                SlotOffer.created_at >= midnight,
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def run_gap_filler(now: datetime | None = None) -> dict[str, int]:
    """Cron : passe du matin + après changement."""
    from jenny.db.session import async_session_factory

    now = _aware(now) or datetime.now(UTC)
    stats = {"businesses": 0, "runs": 0, "sent": 0, "failed": 0}
    async with async_session_factory() as db:
        businesses = (
            (await db.execute(select(Business).where(Business.is_active.is_(True)))).scalars().all()
        )
        ids = [b.id for b in businesses]
    stats["businesses"] = len(ids)
    for bid in ids:
        try:
            async with async_session_factory() as db:
                biz = await db.get(Business, bid)
                if biz is None:
                    continue
                loc = now.astimezone(business_tz(biz)).time()
                reason = None
                if MORNING_FROM <= loc < MORNING_UNTIL and not await _morning_done(db, biz, now):
                    reason = "matin"
                elif await _recent_agenda_change(db, bid, now):
                    reason = "annulation"
                if reason is None:
                    continue
                rep = await fill_gaps_for_business(db, biz, now=now, reason=reason)
                stats["runs"] += 1
                stats["sent"] += rep.sent
                stats["failed"] += rep.failed
        except Exception as exc:  # un salon raté ne bloque pas les autres
            logger.error("gap_filler.business_failed", business_id=str(bid), error=str(exc))
    return stats


# ── déclenché après une annulation (sans worker) ──

_pending: dict[UUID, asyncio.Task] = {}


async def _run_soon(business_id: UUID, delay: float) -> None:
    """Passe « annulation » pour un salon."""
    from jenny.db.session import async_session_factory

    try:
        await asyncio.sleep(delay)
        async with async_session_factory() as db:
            biz = await db.get(Business, business_id)
            if biz is not None and biz.is_active:
                await fill_gaps_for_business(db, biz, reason="annulation")
    except Exception as exc:  # jamais bloquant
        logger.error("gap_filler.after_change_failed", error=str(exc))
    finally:
        _pending.pop(business_id, None)


def schedule_after_change(db: AsyncSession, business_id: UUID, *, delay: float = 2.0) -> bool:
    """Lance une passe après le commit.

    Avec Redis, le worker s'en charge (cron) : on ne fait rien ici.
    """
    from sqlalchemy import event

    from jenny.core.config import get_settings

    if get_settings().redis_url:
        return False
    sync = getattr(db, "sync_session", None)
    if sync is None:
        return False

    def _go(_session) -> None:
        if business_id in _pending:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        _pending[business_id] = loop.create_task(_run_soon(business_id, delay))

    event.listen(sync, "after_commit", _go, once=True)
    return True


# ── stats pour la page ──


async def offer_stats(
    db: AsyncSession, business_id: UUID, *, now: datetime | None = None, days: int = 7
) -> dict[str, int]:
    """Offres envoyées et créneaux remplis."""
    now = _aware(now) or datetime.now(UTC)
    offers = (
        (
            await db.execute(
                select(SlotOffer).where(
                    SlotOffer.business_id == business_id,
                    SlotOffer.created_at >= now - timedelta(days=days),
                )
            )
        )
        .scalars()
        .all()
    )
    sent = [o for o in offers if o.channel and o.customer_id is not None and o.sent_at]
    filled = 0
    if sent:
        since = min(_aware(o.sent_at) for o in sent)
        appts = (
            await db.execute(
                select(Appointment.customer_id, Appointment.created_at).where(
                    Appointment.business_id == business_id,
                    Appointment.customer_id.in_({o.customer_id for o in sent}),
                    Appointment.created_at > since,
                    Appointment.start_at > since,
                    Appointment.status.notin_(NOT_BOOKING),
                )
            )
        ).all()
        by_cust: dict[UUID, list[datetime]] = {}
        for cid, created in appts:
            by_cust.setdefault(cid, []).append(_aware(created))
        for o in sent:
            s = _aware(o.sent_at)
            if any(s < t <= s + FILLED_WINDOW for t in by_cust.get(o.customer_id, [])):
                filled += 1
    return {
        "sent": sum(1 for o in offers if o.channel),
        "failed": sum(1 for o in offers if not o.channel),
        "filled": filled,
    }


__all__ = [
    "GapReport",
    "fill_gaps_for_business",
    "offer_stats",
    "plan_offers",
    "run_gap_filler",
    "schedule_after_change",
    "window_ok",
]
