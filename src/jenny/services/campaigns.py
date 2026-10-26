"""Campagnes de relance du gérant.

Segments calculés en base (dormantes, RDV manqués, jamais revenues,
fidèles), aperçu, envoi avec plafond anti-spam, puis attribution :
une cliente est « revenue » si elle a pris un RDV dans les 30 jours
qui suivent le message, pour une date après le message (dernier
message reçu = celui qui compte).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.orm import lazyload

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import Campaign, CampaignRecipient
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.services.offer_cap import WINDOW, can_offer

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

DORMANT_DAYS = 90
NEW_MIN_DAYS = 30
LOYAL_MIN_VISITS = 10
NO_SHOW_MIN = 2
ATTRIBUTION_DAYS = 30
MAX_MESSAGE_LEN = 600
MIN_MESSAGE_LEN = 10
# anti double clic
RESEND_GUARD = timedelta(seconds=60)

DIRECT_CHANNELS = ("whatsapp", "instagram", "twitter", "snapchat")
# pas une visite
NOT_VISIT = ("cancelled", "blocked", "no_show")
# pas un vrai RDV
NOT_BOOKING = ("cancelled", "blocked")


class CampaignError(ValueError):
    """Demande de campagne refusée."""


@dataclass(frozen=True, slots=True)
class Segment:
    key: str
    label: str
    description: str
    suggestion: str


SEGMENTS: dict[str, Segment] = {
    "dormants": Segment(
        "dormants",
        "Dormantes",
        f"Pas de rendez-vous depuis {DORMANT_DAYS} jours ou plus",
        "Bonjour {prenom}, cela fait un moment ! On serait ravis de vous revoir "
        "au salon. Envie d'un petit créneau cette semaine ?",
    ),
    "no_shows": Segment(
        "no_shows",
        "RDV manqués",
        f"{NO_SHOW_MIN} rendez-vous manqués ou plus",
        "Bonjour {prenom}, on vous garde toujours une place ! Pensez juste à "
        "nous prévenir si vous ne pouvez pas venir, cela aide toute l'équipe.",
    ),
    "nouveaux": Segment(
        "nouveaux",
        "Jamais revenues",
        f"Venues une seule fois, il y a plus de {NEW_MIN_DAYS} jours",
        "Bonjour {prenom}, merci encore pour votre première visite ! "
        "On serait contents de vous revoir, je vous trouve un créneau ?",
    ),
    "fideles": Segment(
        "fideles",
        "Fidèles",
        f"{LOYAL_MIN_VISITS} rendez-vous ou plus",
        "Bonjour {prenom}, merci pour votre fidélité ! Pour vous remercier, "
        "on vous réserve en priorité les nouveaux créneaux du mois.",
    ),
}


def _aware(dt: datetime | str | None) -> datetime | None:
    """Datetime (ou texte SQLite) -> UTC."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ── stats de visite ──


def visit_stats(business_id: UUID, now: datetime):
    """Sous-requête : visites, dernière visite, lapins, à venir."""
    visit = and_(Appointment.status.notin_(NOT_VISIT), Appointment.start_at < now)
    upcoming = and_(Appointment.status.notin_(NOT_BOOKING), Appointment.start_at >= now)
    return (
        select(
            Appointment.customer_id.label("customer_id"),
            func.sum(case((visit, 1), else_=0)).label("visits"),
            func.max(case((visit, Appointment.start_at), else_=None)).label("last_visit"),
            func.min(case((visit, Appointment.start_at), else_=None)).label("first_visit"),
            func.sum(case((Appointment.status == "no_show", 1), else_=0)).label("no_shows"),
            func.sum(case((upcoming, 1), else_=0)).label("upcoming"),
        )
        .where(Appointment.business_id == business_id, Appointment.customer_id.is_not(None))
        .group_by(Appointment.customer_id)
        .subquery("vs")
    )


def segment_condition(key: str, vs, now: datetime):
    """Règle SQL d'un segment."""
    if key == "dormants":
        return and_(
            vs.c.visits >= 1,
            vs.c.last_visit <= now - timedelta(days=DORMANT_DAYS),
            vs.c.upcoming == 0,
        )
    if key == "no_shows":
        return vs.c.no_shows >= NO_SHOW_MIN
    if key == "nouveaux":
        return and_(
            vs.c.visits == 1,
            vs.c.last_visit <= now - timedelta(days=NEW_MIN_DAYS),
            vs.c.upcoming == 0,
        )
    if key == "fideles":
        return vs.c.visits >= LOYAL_MIN_VISITS
    raise CampaignError(f"Segment inconnu : {key}")


def reachable_clause():
    """Joignable : tel, mail ou fil WhatsApp/Insta."""
    direct = exists().where(
        Conversation.customer_id == Customer.id,
        Conversation.channel.in_(DIRECT_CHANNELS),
        Conversation.external_conversation_id.is_not(None),
    )
    return or_(
        and_(Customer.phone.is_not(None), Customer.phone != ""),
        and_(Customer.email.is_not(None), Customer.email != ""),
        direct,
    )


def cap_clause(now: datetime, max_per_week: int = 1):
    """Même règle que can_offer, en SQL."""
    return or_(
        Customer.offer_window_start.is_(None),
        Customer.offer_window_start <= now - WINDOW,
        Customer.offer_window_count < max_per_week,
    )


@dataclass(slots=True)
class Member:
    customer: Customer
    visits: int
    last_visit: datetime | None
    no_shows: int


async def segment_counts(
    db: AsyncSession, business_id: UUID, key: str, now: datetime | None = None
) -> dict[str, int]:
    """Effectif, joignables, contactables cette semaine."""
    now = now or datetime.now(UTC)
    vs = visit_stats(business_id, now)
    reach = and_(Customer.marketing_opt_out_at.is_(None), reachable_clause())
    elig = and_(reach, cap_clause(now))
    row = (
        await db.execute(
            select(
                func.count(Customer.id),
                func.coalesce(func.sum(case((reach, 1), else_=0)), 0),
                func.coalesce(func.sum(case((elig, 1), else_=0)), 0),
            )
            .select_from(Customer)
            .join(vs, vs.c.customer_id == Customer.id)
            .where(
                Customer.business_id == business_id,
                Customer.anonymized_at.is_(None),
                segment_condition(key, vs, now),
            )
        )
    ).one()
    return {"count": int(row[0] or 0), "reachable": int(row[1] or 0), "eligible": int(row[2] or 0)}


async def segment_members(
    db: AsyncSession,
    business_id: UUID,
    key: str,
    now: datetime | None = None,
    *,
    limit: int | None = None,
) -> list[Member]:
    """Clients du segment, plus récents d'abord."""
    now = now or datetime.now(UTC)
    vs = visit_stats(business_id, now)
    q = (
        select(Customer, vs.c.visits, vs.c.last_visit, vs.c.no_shows)
        .join(vs, vs.c.customer_id == Customer.id)
        .where(
            Customer.business_id == business_id,
            Customer.anonymized_at.is_(None),
            segment_condition(key, vs, now),
        )
        .order_by(vs.c.last_visit.desc(), Customer.id)
        .options(lazyload("*"))
    )
    if limit:
        q = q.limit(limit)
    rows = (await db.execute(q)).all()
    return [
        Member(customer=c, visits=int(v or 0), last_visit=_aware(lv), no_shows=int(ns or 0))
        for c, v, lv, ns in rows
    ]


async def direct_conversations(
    db: AsyncSession, business_id: UUID, customer_ids: list[UUID]
) -> dict[UUID, UUID]:
    """Dernier fil WhatsApp/Insta de chaque client."""
    out: dict[UUID, UUID] = {}
    ids = list(customer_ids)
    for i in range(0, len(ids), 500):
        rows = (
            await db.execute(
                select(Conversation.customer_id, Conversation.id)
                .where(
                    Conversation.business_id == business_id,
                    Conversation.customer_id.in_(ids[i : i + 500]),
                    Conversation.channel.in_(DIRECT_CHANNELS),
                    Conversation.external_conversation_id.is_not(None),
                )
                .order_by(Conversation.updated_at.desc())
            )
        ).all()
        for cid, conv_id in rows:
            out.setdefault(cid, conv_id)
    return out


def is_reachable(customer: Customer, convs: dict[UUID, UUID]) -> bool:
    """Un canal existe pour lui écrire."""
    if customer.marketing_opt_out_at is not None:
        return False
    return bool(customer.phone) or bool(customer.email) or customer.id in convs


# ── texte du message ──

_PRENOM_RE = re.compile(r"\s*\{\s*pr[ée]nom\s*\}", re.I)

# alphabet SMS de base
_GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = set("^{}\\[~]|€")
# tiret, apostrophes, point
_NAME_PUNCT = "-'." + chr(0x2019)


def first_name(full_name: str | None) -> str:
    """Prénom affichable, ou vide."""
    parts = (full_name or "").strip().split()
    if not parts:
        return ""
    tok = parts[0]
    if len(tok) > 30 or not all(ch.isalpha() or ch in _NAME_PUNCT for ch in tok):
        # pas un vrai prénom
        return ""
    if not any(ch.isalpha() for ch in tok):
        return ""
    return tok[:1].upper() + tok[1:]


def footer(salon: str) -> str:
    """Signature : IA transparente + STOP."""
    return (
        f"\n- {salon}, via Jenny (assistante virtuelle). "
        "Répondez STOP pour ne plus recevoir d'offres."
    )


def render_message(template: str, *, name: str, salon: str) -> str:
    """Remplace {prenom} et ajoute la signature."""
    repl = f" {name}" if name else ""
    # fonction : pas de \1 interprété
    body = _PRENOM_RE.sub(lambda _m: repl, template.strip())
    body = re.sub(r"^[\s,;:]+", "", body)
    body = body[:1].upper() + body[1:]
    return body + footer(salon)


def is_gsm(text: str) -> bool:
    """Que des caractères SMS de base ?"""
    return all(ch in _GSM7 or ch in _GSM7_EXT for ch in text or "")


def sms_parts(text: str) -> int:
    """Nombre de SMS facturés."""
    if not text:
        return 0
    if is_gsm(text):
        size = sum(2 if ch in _GSM7_EXT else 1 for ch in text)
        return 1 if size <= 160 else -(-size // 153)
    return 1 if len(text) <= 70 else -(-len(text) // 67)


def validate_message(message: str) -> str:
    """Texte propre, sinon erreur."""
    text = (message or "").strip()
    if len(text) < MIN_MESSAGE_LEN:
        raise CampaignError("Le message est trop court.")
    if len(text) > MAX_MESSAGE_LEN:
        raise CampaignError(f"Le message dépasse {MAX_MESSAGE_LEN} caractères.")
    return text


# ── envoi ──


async def create_campaign(
    db: AsyncSession,
    *,
    business_id: UUID,
    segment: str,
    message: str,
    created_by: str | None = None,
    now: datetime | None = None,
) -> Campaign:
    """Crée la campagne (l'envoi suit à part)."""
    now = now or datetime.now(UTC)
    if segment not in SEGMENTS:
        raise CampaignError(f"Segment inconnu : {segment}")
    text = validate_message(message)
    recent = (
        await db.execute(
            select(Campaign.id).where(
                Campaign.business_id == business_id,
                Campaign.segment == segment,
                Campaign.created_at >= now - RESEND_GUARD,
            )
        )
    ).first()
    if recent is not None:
        raise CampaignError("Une campagne vient déjà de partir pour ce segment.")
    counts = await segment_counts(db, business_id, segment, now)
    camp = Campaign(
        business_id=business_id,
        segment=segment,
        message=text,
        status="sending",
        target_count=counts["count"],
        created_by=created_by,
        created_at=now,
    )
    db.add(camp)
    await db.flush()
    return camp


async def deliver_campaign(
    db: AsyncSession, campaign_id: UUID, *, now: datetime | None = None
) -> dict[str, int]:
    """Envoie à chaque client du segment, plafond respecté.

    Rejouable : un client déjà traité n'est jamais relancé. Une cliente
    qui plante (nom bizarre, canal HS) ne bloque pas les suivantes.
    """
    camp = await db.get(Campaign, campaign_id)
    if camp is None:
        return {"sent": 0, "skipped": 0}
    bid = camp.business_id
    biz = await db.get(Business, bid)
    salon = (biz.name if biz else None) or "Votre salon"
    ref = now or datetime.now(UTC)
    members = await segment_members(db, bid, camp.segment, ref)
    done = set(
        (
            await db.execute(
                select(CampaignRecipient.customer_id).where(
                    CampaignRecipient.campaign_id == camp.id
                )
            )
        ).scalars()
    )
    convs = await direct_conversations(db, bid, [m.customer.id for m in members])
    camp_id, message = camp.id, camp.message
    # données figées : survit au rollback
    targets = [
        (m.customer.id, m.customer.full_name, convs.get(m.customer.id))
        for m in members
        if m.customer.id not in done
        # STOP, plafond, injoignable : non
        and is_reachable(m.customer, convs)
        and can_offer(m.customer, ref)
    ]
    for cid, full_name, conv_id in targets:
        try:
            await _deliver_one(
                db,
                camp_id=camp_id,
                bid=bid,
                cid=cid,
                text=render_message(message, name=first_name(full_name), salon=salon),
                salon=salon,
                conv_id=conv_id,
                sent_at=now or datetime.now(UTC),
            )
        except Exception as exc:  # une cliente ratée, on continue
            await db.rollback()
            logger.error("campaign.recipient_failed", campaign_id=str(camp_id), error=str(exc))

    return await _close_campaign(db, camp_id, len(members))


async def _deliver_one(
    db: AsyncSession,
    *,
    camp_id: UUID,
    bid: UUID,
    cid: UUID,
    text: str,
    salon: str,
    conv_id: UUID | None,
    sent_at: datetime,
) -> None:
    """Trace puis envoie à une cliente."""
    from jenny.notifications.outbound import notify_customer

    # trace avant envoi
    key = {"campaign_id": camp_id, "customer_id": cid}
    if not await insert_once(db, CampaignRecipient, {**key, "sent_at": sent_at}, list(key)):
        return
    await db.commit()
    canal = await notify_customer(
        db,
        business_id=bid,
        customer_id=cid,
        conversation_id=conv_id,
        text=text,
        subject=f"{salon} pense à vous",
        commercial=True,
    )
    if canal:
        await db.execute(
            update(CampaignRecipient)
            .where(
                CampaignRecipient.campaign_id == camp_id,
                CampaignRecipient.customer_id == cid,
            )
            .values(channel=canal)
            .execution_options(synchronize_session=False)
        )
    await db.commit()


async def _close_campaign(
    db: AsyncSession, camp_id: UUID, members: int, *, status: str = "sent"
) -> dict[str, int]:
    """Compteurs + statut final."""
    camp = await db.get(Campaign, camp_id)
    if camp is None:
        return {"sent": 0, "skipped": 0}
    sent = int(
        (
            await db.execute(
                select(func.count()).where(
                    CampaignRecipient.campaign_id == camp.id,
                    CampaignRecipient.channel.is_not(None),
                )
            )
        ).scalar_one()
    )
    camp.target_count = max(camp.target_count, members)
    camp.sent_count = sent
    camp.skipped_count = max(0, camp.target_count - sent)
    camp.status = status
    await db.commit()
    logger.info(
        "campaign.closed",
        campaign_id=str(camp.id),
        sent=sent,
        target=camp.target_count,
        status=status,
    )
    return {"sent": sent, "skipped": camp.skipped_count}


async def deliver_campaign_job(campaign_id: UUID) -> None:
    """Envoi en tâche de fond, session à part."""
    from jenny.db.session import async_session_factory

    try:
        async with async_session_factory() as db:
            await deliver_campaign(db, campaign_id)
    except Exception as exc:  # jamais bloquant
        logger.error("campaign.deliver_failed", campaign_id=str(campaign_id), error=str(exc))
        try:
            # plus jamais « en cours »
            async with async_session_factory() as db:
                await _close_campaign(db, campaign_id, 0, status="failed")
        except Exception as exc2:  # base HS
            logger.error("campaign.mark_failed_failed", error=str(exc2))


# envoi coupé net (redémarrage)
STALE_SENDING = timedelta(minutes=15)
RESUME_MAX_AGE = timedelta(hours=24)


async def resume_stale_campaigns(now: datetime | None = None, *, limit: int = 5) -> int:
    """Reprend les envois restés « en cours »."""
    from jenny.db.session import async_session_factory
    from jenny.services.gap_filler import in_send_hours

    now = now or datetime.now(UTC)
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(Campaign.id, Campaign.created_at, Campaign.business_id)
                .where(Campaign.status == "sending", Campaign.created_at <= now - STALE_SENDING)
                .order_by(Campaign.created_at.asc())
                .limit(limit)
            )
        ).all()
        todo: list[UUID] = []
        for cid, created, bid in rows:
            if (_aware(created) or now) < now - RESUME_MAX_AGE:
                # trop vieux pour envoyer
                await _close_campaign(db, cid, 0, status="failed")
                continue
            biz = await db.get(Business, bid)
            if biz is not None and in_send_hours(biz, now):
                todo.append(cid)
    for cid in todo:
        logger.info("campaign.resume", campaign_id=str(cid))
        await deliver_campaign_job(cid)
    return len(todo)


# ── attribution ──


def _dialect(db: AsyncSession) -> str:
    """Nom du moteur SQL."""
    try:
        return db.get_bind().dialect.name
    except Exception:
        return "postgresql"


def _plus_days(col, days: int, dialect: str):
    """col + N jours, selon le moteur."""
    if dialect == "sqlite":
        return func.datetime(col, f"+{int(days)} days")
    return col + timedelta(days=days)


async def insert_once(db: AsyncSession, model, values: dict, keys: list[str]) -> bool:
    """INSERT, ou rien si la ligne existe."""
    if _dialect(db) == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    stmt = insert(model).values(**values).on_conflict_do_nothing(index_elements=keys)
    res = await db.execute(stmt)
    return (res.rowcount or 0) > 0


@dataclass(slots=True)
class Attribution:
    returned: dict[UUID, set] = field(default_factory=dict)
    revenue_cents: dict[UUID, int] = field(default_factory=dict)


async def attribute(db: AsyncSession, business_id: UUID) -> Attribution:
    """Qui est revenu grâce à quelle campagne."""
    from jenny.services.prestation_service import find_prestation, load_active_prestations

    deadline = _plus_days(CampaignRecipient.sent_at, ATTRIBUTION_DAYS, _dialect(db))
    rows = (
        await db.execute(
            select(
                CampaignRecipient.campaign_id,
                CampaignRecipient.customer_id,
                CampaignRecipient.sent_at,
                Appointment.id,
                Appointment.title,
            )
            .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
            .join(
                Appointment,
                and_(
                    Appointment.business_id == Campaign.business_id,
                    Appointment.customer_id == CampaignRecipient.customer_id,
                    Appointment.created_at > CampaignRecipient.sent_at,
                    Appointment.created_at <= deadline,
                    # visite saisie après coup : non
                    Appointment.start_at > CampaignRecipient.sent_at,
                    Appointment.status.notin_(NOT_BOOKING),
                ),
            )
            .where(Campaign.business_id == business_id, CampaignRecipient.channel.is_not(None))
        )
    ).all()

    # dernier message reçu gagne
    best: dict[Any, tuple] = {}
    for camp_id, cust_id, sent_at, appt_id, title in rows:
        cur = best.get(appt_id)
        if cur is None or (_aware(sent_at) or datetime.min.replace(tzinfo=UTC)) > cur[2]:
            best[appt_id] = (
                camp_id,
                cust_id,
                _aware(sent_at) or datetime.min.replace(tzinfo=UTC),
                title,
            )

    out = Attribution()
    prestations = await load_active_prestations(db, business_id) if best else []
    for camp_id, cust_id, _sent, title in best.values():
        out.returned.setdefault(camp_id, set()).add(cust_id)
        p = find_prestation(prestations, title or "") if prestations else None
        if p is not None and p.price_cents:
            out.revenue_cents[camp_id] = out.revenue_cents.get(camp_id, 0) + int(p.price_cents)
    return out


async def campaign_history(
    db: AsyncSession, business_id: UUID, *, now: datetime | None = None, limit: int = 30
) -> list[dict[str, Any]]:
    """Historique avec le résultat attribué."""
    now = now or datetime.now(UTC)
    camps = (
        (
            await db.execute(
                select(Campaign)
                .where(Campaign.business_id == business_id)
                .order_by(Campaign.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not camps:
        return []
    attr = await attribute(db, business_id)
    out = []
    for c in camps:
        created = _aware(c.created_at) or now
        seg = SEGMENTS.get(c.segment)
        out.append(
            {
                "id": c.id,
                "segment": c.segment,
                "segment_label": seg.label if seg else c.segment,
                "message": c.message,
                "status": c.status,
                "created_at": created,
                "created_by": c.created_by,
                "target_count": c.target_count,
                "sent_count": c.sent_count,
                "skipped_count": c.skipped_count,
                "returned_count": len(attr.returned.get(c.id, ())),
                "revenue_eur": round(attr.revenue_cents.get(c.id, 0) / 100, 2),
                "window_ends_at": created + timedelta(days=ATTRIBUTION_DAYS),
                "window_open": now < created + timedelta(days=ATTRIBUTION_DAYS),
            }
        )
    return out
