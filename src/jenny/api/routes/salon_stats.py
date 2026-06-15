"""Statistiques métier du salon — agrégations réelles pour le tableau de bord.

Donne au coiffeur une vue chiffrée de son activité : prestations populaires,
heures de pointe, taux de remplissage, taux d'annulation (proxy no-show), clients
fidèles vs nouveaux, estimation de chiffre d'affaires à venir, et l'état des
acomptes / de la liste d'attente (anti-no-show). Tout est calculé en base, sans
inventer : si une donnée manque, le chiffre est simplement 0.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.review import Review
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services.availability import _DAY_KEYS, _DEFAULT_HOURS, business_tz

logger = get_logger(__name__)

router = APIRouter(prefix="/salon", tags=["Salon stats"])

_WD_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class NameCount(BaseModel):
    name: str
    count: int


class HourCount(BaseModel):
    hour: int
    count: int


class DepositStats(BaseModel):
    enabled: bool
    pending: int
    paid: int
    collected_eur: float


class WaitlistStats(BaseModel):
    waiting: int
    notified: int


class SalonStats(BaseModel):
    range_days: int
    appointments_total: int  # sur la fenêtre passée
    upcoming: int
    completed: int
    cancelled: int
    cancellation_rate_pct: float
    fill_rate_pct: float
    top_prestations: list[NameCount]
    peak_hours: list[HourCount]
    busiest_day: str | None
    clients_total: int
    loyal_clients: int
    new_clients: int
    revenue_upcoming_eur: float
    deposits: DepositStats
    waitlist: WaitlistStats
    average_rating: float | None = None
    reviews_count: int = 0
    no_show: int = 0


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _capacity_slots(business: Business | None, start_day, end_day) -> int:
    """Nombre de créneaux de 30 min ouvrables entre deux jours (selon les horaires).

    Sert de dénominateur au taux de remplissage : une approximation honnête de la
    capacité d'accueil sur la période passée.
    """
    hours = (business.business_hours if business else None) or _DEFAULT_HOURS
    total = 0
    day = start_day
    while day <= end_day:
        window = hours.get(_DAY_KEYS[day.weekday()])
        if window and len(window) == 2:
            try:
                oh, om = (int(x) for x in window[0].split(":"))
                ch, cm = (int(x) for x in window[1].split(":"))
                minutes = (ch * 60 + cm) - (oh * 60 + om)
                if minutes > 0:
                    total += minutes // 30
            except (ValueError, AttributeError):
                pass
        day += timedelta(days=1)
    return total


@router.get("/stats", response_model=SalonStats)
async def salon_stats(
    db: DbSession,
    principal: CurrentUser,
    range_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SalonStats:
    """Statistiques métier du salon courant sur les ``range_days`` derniers jours."""
    bid = principal.business_id
    empty = SalonStats(
        range_days=range_days, appointments_total=0, upcoming=0, completed=0,
        cancelled=0, cancellation_rate_pct=0.0, fill_rate_pct=0.0,
        top_prestations=[], peak_hours=[], busiest_day=None,
        clients_total=0, loyal_clients=0, new_clients=0, revenue_upcoming_eur=0.0,
        deposits=DepositStats(enabled=False, pending=0, paid=0, collected_eur=0.0),
        waitlist=WaitlistStats(waiting=0, notified=0),
    )
    if bid is None:
        return empty

    business = await db.get(Business, bid)
    tz = business_tz(business)
    now = datetime.now(UTC)
    since = now - timedelta(days=range_days)

    # Fenêtre élargie : passé (analyse) + futur proche (à venir / CA / acomptes).
    rows = list(
        (
            await db.execute(
                select(Appointment).where(
                    Appointment.business_id == bid,
                    Appointment.start_at >= since,
                    Appointment.start_at < now + timedelta(days=120),
                )
            )
        ).scalars().all()
    )

    past = [a for a in rows if _aware(a.start_at) < now]
    past_active = [a for a in past if a.status != "blocked"]
    completed = sum(1 for a in past_active if a.status in ("completed", "confirmed"))
    cancelled = sum(1 for a in past_active if a.status == "cancelled")
    no_show = sum(1 for a in past_active if a.status == "no_show")
    upcoming = sum(
        1 for a in rows if _aware(a.start_at) >= now and a.status not in ("cancelled", "blocked")
    )
    total_past = len(past_active)
    cancel_rate = round(100 * cancelled / total_past, 1) if total_past else 0.0

    # Taux de remplissage : RDV honorés (hors annulés/bloqués) / capacité ouvrable.
    booked = sum(1 for a in past_active if a.status != "cancelled")
    capacity = _capacity_slots(business, since.astimezone(tz).date(), now.astimezone(tz).date())
    fill_rate = round(min(100.0, 100 * booked / capacity), 1) if capacity else 0.0

    # Prestations populaires + heures de pointe + jour le plus chargé (RDV honorés).
    honored = [a for a in past_active if a.status != "cancelled"]
    presta_counter: Counter[str] = Counter(a.title for a in honored if a.title)
    hour_counter: Counter[int] = Counter(_aware(a.start_at).astimezone(tz).hour for a in honored)
    day_counter: Counter[int] = Counter(
        _aware(a.start_at).astimezone(tz).weekday() for a in honored
    )
    top_prestations = [NameCount(name=n, count=c) for n, c in presta_counter.most_common(6)]
    peak_hours = [
        HourCount(hour=h, count=c) for h, c in sorted(hour_counter.most_common(4))
    ]
    busiest_day = _WD_FR[day_counter.most_common(1)[0][0]] if day_counter else None

    # Clients fidèles (≥2 RDV honorés) vs nouveaux (tous RDV non annulés/bloqués, all-time).
    client_counts = (
        await db.execute(
            select(Appointment.customer_id, func.count(Appointment.id))
            .where(
                Appointment.business_id == bid,
                Appointment.customer_id.is_not(None),
                Appointment.status.notin_(["cancelled", "blocked"]),
            )
            .group_by(Appointment.customer_id)
        )
    ).all()
    loyal = sum(1 for _cid, n in client_counts if n >= 2)
    clients_total = len(client_counts)
    new_clients = clients_total - loyal

    # CA estimé à venir (prestations reconnues dans le catalogue).
    revenue_eur = await _estimate_upcoming_revenue(db, bid, rows, now)

    # Acomptes (sur toute la fenêtre).
    dep_pending = sum(1 for a in rows if a.deposit_status == "pending")
    dep_paid = sum(1 for a in rows if a.deposit_status == "paid")
    collected = sum((a.deposit_cents or 0) for a in rows if a.deposit_status == "paid") / 100

    # Liste d'attente.
    wl = (
        await db.execute(
            select(WaitlistEntry.status, func.count(WaitlistEntry.id))
            .where(WaitlistEntry.business_id == bid)
            .group_by(WaitlistEntry.status)
        )
    ).all()
    wl_map = {s: n for s, n in wl}

    # Avis clients (note moyenne).
    rev = (
        await db.execute(
            select(func.count(Review.id), func.avg(Review.rating)).where(
                Review.business_id == bid
            )
        )
    ).first()
    reviews_count = int(rev[0] or 0) if rev else 0
    average_rating = round(float(rev[1]), 2) if rev and rev[1] is not None else None

    return SalonStats(
        range_days=range_days,
        appointments_total=total_past,
        upcoming=upcoming,
        completed=completed,
        cancelled=cancelled,
        cancellation_rate_pct=cancel_rate,
        fill_rate_pct=fill_rate,
        top_prestations=top_prestations,
        peak_hours=peak_hours,
        busiest_day=busiest_day,
        clients_total=clients_total,
        loyal_clients=loyal,
        new_clients=new_clients,
        revenue_upcoming_eur=round(revenue_eur, 2),
        deposits=DepositStats(
            enabled=bool(business and business.deposit_enabled),
            pending=dep_pending,
            paid=dep_paid,
            collected_eur=round(collected, 2),
        ),
        waitlist=WaitlistStats(
            waiting=int(wl_map.get("waiting", 0)),
            notified=int(wl_map.get("notified", 0)),
        ),
        average_rating=average_rating,
        reviews_count=reviews_count,
        no_show=no_show,
    )


async def _estimate_upcoming_revenue(db, bid, rows, now: datetime) -> float:
    """Estime le CA des RDV à venir en associant le titre au catalogue de prestations."""
    from jenny.services.prestation_service import _norm, load_active_prestations

    prestations = await load_active_prestations(db, bid)
    price_map = {_norm(p.name): p.price_cents for p in prestations if p.price_cents}
    if not price_map:
        return 0.0
    total_cents = 0
    for a in rows:
        if _aware(a.start_at) < now or a.status in ("cancelled", "blocked"):
            continue
        nt = _norm(a.title or "")
        cents = next((c for n, c in price_map.items() if n and (n in nt or nt in n)), None)
        if cents:
            total_cents += cents
    return total_cents / 100
