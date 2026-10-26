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
from sqlalchemy import and_, func, select

from jenny.api.dependencies import CurrentUser, DbSession  # noqa: TC001
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
    # tout compté en SQL
    a = Appointment
    window = (a.business_id == bid, a.start_at >= since, a.start_at < now + timedelta(days=120))
    past = and_(a.start_at < now, a.status != "blocked")
    honored = and_(past, a.status != "cancelled")
    upcoming_ok = and_(a.start_at >= now, a.status.notin_(["cancelled", "blocked"]))

    agg = (
        await db.execute(
            select(
                func.count(a.id).filter(past),
                func.count(a.id).filter(past, a.status.in_(["completed", "confirmed"])),
                func.count(a.id).filter(past, a.status == "cancelled"),
                func.count(a.id).filter(past, a.status == "no_show"),
                func.count(a.id).filter(upcoming_ok),
                func.count(a.id).filter(a.deposit_status == "pending"),
                func.count(a.id).filter(a.deposit_status == "paid"),
                func.coalesce(func.sum(a.deposit_cents).filter(a.deposit_status == "paid"), 0),
                *_side_counts(bid),
            ).where(*window)
        )
    ).one()
    (
        total_past, completed, cancelled, no_show, upcoming,
        dep_pending, dep_paid, collected_cents,
        clients_total, loyal, wl_waiting, wl_notified, reviews_count, avg_rating,
    ) = agg
    total_past, cancelled = int(total_past or 0), int(cancelled or 0)
    cancel_rate = round(100 * cancelled / total_past, 1) if total_past else 0.0

    # Taux de remplissage : RDV honorés (hors annulés/bloqués) / capacité ouvrable.
    booked = total_past - cancelled
    capacity = _capacity_slots(business, since.astimezone(tz).date(), now.astimezone(tz).date())
    fill_rate = round(min(100.0, 100 * booked / capacity), 1) if capacity else 0.0

    # par titre : top et CA
    by_title = (
        await db.execute(
            select(a.title, func.count(a.id).filter(honored), func.count(a.id).filter(upcoming_ok))
            .where(*window)
            .group_by(a.title)
        )
    ).all()
    honored_titles = sorted(
        ((t, int(n)) for t, n, _u in by_title if t and n), key=lambda x: (-x[1], x[0])
    )
    top_prestations = [NameCount(name=t, count=n) for t, n in honored_titles[:6]]
    upcoming_titles = {(t or ""): int(u) for t, _n, u in by_title if u}

    # fuseau du salon, en Python
    starts =(await db.execute(select(a.start_at).where(*window, honored))).scalars().all()
    hour_counter: Counter[int] = Counter(_aware(s).astimezone(tz).hour for s in starts)
    day_counter: Counter[int] = Counter(_aware(s).astimezone(tz).weekday() for s in starts)
    peak_hours = [
        HourCount(hour=h, count=c) for h, c in sorted(hour_counter.most_common(4))
    ]
    busiest_day = _WD_FR[day_counter.most_common(1)[0][0]] if day_counter else None

    # CA estimé à venir (prestations reconnues dans le catalogue).
    revenue_eur = await _estimate_upcoming_revenue(db, bid, upcoming_titles)

    clients_total, loyal = int(clients_total or 0), int(loyal or 0)
    average_rating = round(float(avg_rating), 2) if avg_rating is not None else None

    return SalonStats(
        range_days=range_days,
        appointments_total=total_past,
        upcoming=int(upcoming or 0),
        completed=int(completed or 0),
        cancelled=cancelled,
        cancellation_rate_pct=cancel_rate,
        fill_rate_pct=fill_rate,
        top_prestations=top_prestations,
        peak_hours=peak_hours,
        busiest_day=busiest_day,
        clients_total=clients_total,
        loyal_clients=loyal,
        new_clients=clients_total - loyal,
        revenue_upcoming_eur=round(revenue_eur, 2),
        deposits=DepositStats(
            enabled=bool(business and business.deposit_enabled),
            pending=int(dep_pending or 0),
            paid=int(dep_paid or 0),
            collected_eur=round(int(collected_cents or 0) / 100, 2),
        ),
        waitlist=WaitlistStats(waiting=int(wl_waiting or 0), notified=int(wl_notified or 0)),
        average_rating=average_rating,
        reviews_count=int(reviews_count or 0),
        no_show=int(no_show or 0),
    )


def _side_counts(bid) -> list:
    """Clients, attente et avis en sous-requêtes."""
    a, w = Appointment, WaitlistEntry
    # Clients fidèles (≥2 RDV honorés) vs nouveaux (tous RDV non annulés/bloqués, all-time).
    per_client = (
        select(a.customer_id, func.count(a.id).label("n"))
        .where(
            a.business_id == bid,
            a.customer_id.is_not(None),
            a.status.notin_(["cancelled", "blocked"]),
        )
        .group_by(a.customer_id)
        .subquery()
    )
    return [
        select(func.count()).select_from(per_client).scalar_subquery(),
        select(func.count()).select_from(per_client).where(per_client.c.n >= 2).scalar_subquery(),
        select(func.count(w.id)).where(w.business_id == bid, w.status == "waiting").scalar_subquery(),
        select(func.count(w.id)).where(w.business_id == bid, w.status == "notified").scalar_subquery(),
        select(func.count(Review.id)).where(Review.business_id == bid).scalar_subquery(),
        select(func.avg(Review.rating)).where(Review.business_id == bid).scalar_subquery(),
    ]


async def _estimate_upcoming_revenue(db, bid, upcoming_titles: dict[str, int]) -> float:
    """Estime le CA des RDV à venir en associant le titre au catalogue de prestations."""
    if not upcoming_titles:
        return 0.0  # rien à venir
    from jenny.services.prestation_service import _norm, load_active_prestations

    prestations = await load_active_prestations(db, bid)
    price_map = {_norm(p.name): p.price_cents for p in prestations if p.price_cents}
    if not price_map:
        return 0.0
    total_cents = 0
    for title, count in upcoming_titles.items():
        nt = _norm(title)
        cents = next((c for n, c in price_map.items() if n and (n in nt or nt in n)), None)
        if cents:
            total_cents += cents * count
    return total_cents / 100
