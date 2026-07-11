"""Moteur de disponibilités : créneaux libres réels d'un salon.

Créneaux d'un jour = horaires d'ouverture (``business_hours``, dans le fuseau du
salon) découpés à la durée de la prestation, MOINS les rendez-vous existants
(non annulés, créneaux bloqués inclus) et les créneaux déjà passés.

Utilisé par Jenny pour PROPOSER des créneaux au client (« mardi j'ai libre à 10h,
14h ou 16h ») et pour vérifier qu'une réservation ne chevauche rien.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.domain.models.business import Business

logger = get_logger(__name__)

# Lundi=0 … Dimanche=6 (aligné sur ``date.weekday()``).
_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DEFAULT_HOURS: dict[str, list[str] | None] = {
    "mon": ["09:00", "19:00"],
    "tue": ["09:00", "19:00"],
    "wed": ["09:00", "19:00"],
    "thu": ["09:00", "19:00"],
    "fri": ["09:00", "19:00"],
    "sat": ["09:00", "18:00"],
    "sun": None,
}


def business_tz(business: Business | None) -> ZoneInfo:
    try:
        return ZoneInfo((business.timezone if business else None) or "Europe/Paris")
    except Exception:
        return ZoneInfo("Europe/Paris")


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        h, m = value.split(":")
        if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
            return int(h), int(m)
    except (ValueError, AttributeError):
        pass
    return None


def _candidate_slots(business: Business, day: date, duration_min: int) -> list[datetime]:
    """Créneaux candidats (début, en UTC) du jour selon les horaires d'ouverture."""
    tz = business_tz(business)
    hours = (business.business_hours if business else None) or _DEFAULT_HOURS
    window = hours.get(_DAY_KEYS[day.weekday()])
    if not window or len(window) != 2:
        return []
    open_hm, close_hm = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    if open_hm is None or close_hm is None:
        return []
    start = datetime(day.year, day.month, day.day, open_hm[0], open_hm[1], tzinfo=tz)
    close = datetime(day.year, day.month, day.day, close_hm[0], close_hm[1], tzinfo=tz)
    step = timedelta(minutes=duration_min)
    out: list[datetime] = []
    cur = start
    while cur + step <= close:
        out.append(cur.astimezone(UTC))
        cur += step
    return out


async def is_day_closed(
    db: AsyncSession,
    business_id: UUID,
    day: date,
    *,
    business: Business | None = None,
) -> bool:
    """Vrai si le salon est fermé ce jour-là.

    Couvre les DEUX cas : fermeture exceptionnelle (congé, férié…) ET fermeture
    hebdomadaire (pas de fenêtre d'ouverture ce jour de la semaine — ex. lundi).
    Sans cette seconde branche, « déplace mon RDV à lundi » réservait un jour
    où le salon n'ouvre jamais.
    """
    from jenny.domain.models.business_closure import BusinessClosure

    try:
        row = (
            await db.execute(
                select(BusinessClosure.id)
                .where(
                    BusinessClosure.business_id == business_id,
                    BusinessClosure.start_date <= day,
                    BusinessClosure.end_date >= day,
                )
                .limit(1)
            )
        ).first()
        if row is not None:
            return True
    except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
        logger.warning("availability.closure_check_error", error=str(exc))
        return False

    # Fermeture hebdomadaire : aucune fenêtre d'ouverture pour ce jour de semaine.
    if business is None:
        from jenny.domain.models.business import Business as _Business

        business = await db.get(_Business, business_id)
    hours = (business.business_hours if business else None) or _DEFAULT_HOURS
    window = hours.get(_DAY_KEYS[day.weekday()])
    return not (window and len(window) == 2)


async def free_slots_for_day(
    db: AsyncSession,
    business_id: UUID,
    day: date,
    duration_min: int = 30,
    *,
    business: Business | None = None,
) -> list[datetime]:
    """Créneaux libres (début, UTC) d'un jour pour une durée donnée."""
    from jenny.domain.models.business import Business as _Business

    if business is None:
        business = await db.get(_Business, business_id)
    # Fermeture exceptionnelle → aucun créneau ce jour-là.
    if await is_day_closed(db, business_id, day):
        return []
    candidates = _candidate_slots(business, day, duration_min)
    if not candidates:
        return []
    now = datetime.now(UTC)
    candidates = [s for s in candidates if s > now]
    if not candidates:
        return []

    step = timedelta(minutes=duration_min)
    win_start, win_end = candidates[0], candidates[-1] + step
    booked = (
        await db.execute(
            select(Appointment.start_at, Appointment.end_at).where(
                Appointment.business_id == business_id,
                Appointment.status != "cancelled",
                Appointment.start_at < win_end,
                Appointment.end_at > win_start,
            )
        )
    ).all()

    def _taken(s: datetime) -> bool:
        s_end = s + step
        for bs, be in booked:
            bs_u = bs if bs.tzinfo else bs.replace(tzinfo=UTC)
            be_u = be if be.tzinfo else be.replace(tzinfo=UTC)
            if s < be_u and s_end > bs_u:
                return True
        return False

    return [s for s in candidates if not _taken(s)]


async def next_free_slots(
    db: AsyncSession,
    business_id: UUID,
    duration_min: int = 30,
    *,
    from_day: date | None = None,
    max_days: int = 14,
    limit: int = 4,
) -> list[datetime]:
    """Premiers créneaux libres à partir d'un jour, en balayant les jours suivants."""
    from jenny.domain.models.business import Business as _Business

    business = await db.get(_Business, business_id)
    tz = business_tz(business)
    start = from_day or datetime.now(tz).date()
    found: list[datetime] = []
    for i in range(max_days):
        day = start + timedelta(days=i)
        slots = await free_slots_for_day(
            db, business_id, day, duration_min, business=business
        )
        found.extend(slots)
        if len(found) >= limit:
            break
    return found[:limit]


def format_slots_fr(slots: list[datetime], tz: ZoneInfo, *, with_day: bool = False) -> str:
    """Formate des créneaux pour Jenny : « 10h00, 14h00, 16h00 » (ou avec le jour)."""
    _days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    labels: list[str] = []
    for s in slots:
        loc = s.astimezone(tz)
        t = loc.strftime("%Hh%M")
        labels.append(f"{_days[loc.weekday()]} {loc.day:02d}/{loc.month:02d} à {t}" if with_day else t)
    return ", ".join(labels)
