"""Moteur de disponibilités : créneaux libres réels d'un salon.

Sans coiffeur actif : un fauteuil implicite, calcul historique inchangé
(horaires découpés à la durée, moins les RDV et le passé).

Avec coiffeurs : départs toutes les 15 min, libre s'il reste un coiffeur
actif, compétent, présent et sans RDV sur lui. Un RDV sans coiffeur prend un
fauteuil ; un « blocked » sans coiffeur bloque tout le salon. Un RDV d'un
coiffeur en pause n'occupe que lui (même règle que la contrainte EXCLUDE).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.staff import Staff, StaffSkill

if TYPE_CHECKING:
    from collections.abc import Iterable
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

# pas de la grille multi-coiffeurs
SLOT_STEP_MIN = 15


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


def _aware(dt: datetime) -> datetime:
    """SQLite rend du naïf : on force UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


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


# ── Coiffeurs ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class StaffPool:
    """Coiffeurs actifs d'un salon."""

    members: list[Staff] = field(default_factory=list)
    skills: dict[UUID, set[UUID]] = field(default_factory=dict)

    @property
    def has_staff(self) -> bool:
        return bool(self.members)

    def get(self, staff_id: UUID | None) -> Staff | None:
        """Coiffeur actif par id."""
        return next((m for m in self.members if m.id == staff_id), None)

    def can_do(self, staff_id: UUID, prestation_ids: Iterable[UUID] | None) -> bool:
        """Compétent pour ces prestations ?"""
        wanted = list(prestation_ids or [])
        if not wanted:
            return True
        known = self.skills.get(staff_id) or set()
        if not known:
            # rien coché : dépend du drapeau
            member = self.get(staff_id)
            return member is None or bool(member.all_services)
        return all(p in known for p in wanted)


@dataclass(slots=True)
class StaffPick:
    """Qui peut prendre un créneau."""

    free: bool
    staff: Staff | None = None
    has_staff: bool = False


async def load_staff_pool(db: AsyncSession, business_id: UUID) -> StaffPool:
    """Charge les coiffeurs actifs et leurs compétences."""
    members = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.business_id == business_id, Staff.is_active.is_(True))
                .order_by(Staff.created_at.asc(), Staff.display_name.asc(), Staff.id.asc())
            )
        ).scalars().all()
    )
    skills: dict[UUID, set[UUID]] = {}
    if members:
        rows = (
            await db.execute(
                select(StaffSkill.staff_id, StaffSkill.prestation_id).where(
                    StaffSkill.staff_id.in_([m.id for m in members])
                )
            )
        ).all()
        for sid, pid in rows:
            skills.setdefault(sid, set()).add(pid)
    return StaffPool(members=members, skills=skills)


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def match_staff(pool: StaffPool, text: str | None) -> Staff | None:
    """Retrouve un coiffeur par son prénom."""
    q = _norm(text or "")
    if not q:
        return None
    for m in pool.members:
        name = _norm(m.display_name)
        if q == name or q == name.split(" ")[0]:
            return m
    return None


def staff_in_text(pool: StaffPool, text: str | None) -> Staff | None:
    """Coiffeur cité dans une phrase."""
    words = re.findall(r"[a-z0-9]+", _norm(text or ""))
    if not words:
        return None
    joined = f" {' '.join(words)} "
    # nom complet d'abord, puis prénom
    for full in (True, False):
        for m in pool.members:
            parts = re.findall(r"[a-z0-9]+", _norm(m.display_name))
            if not parts:
                continue
            key = " ".join(parts) if full else parts[0]
            if f" {key} " in joined:
                return m
    return None


def _window(
    hours: dict[str, Any] | None, day: date
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Ouverture / fermeture d'un jour."""
    if not isinstance(hours, dict):
        return None
    win = hours.get(_DAY_KEYS[day.weekday()])
    if not win or len(win) != 2:
        return None
    a, b = _parse_hhmm(win[0]), _parse_hhmm(win[1])
    if a is None or b is None:
        return None
    return a, b


def _local(day: date, hm: tuple[int, int], tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=tz)


def _salon_bounds(business: Business | None, day: date) -> tuple[datetime, datetime] | None:
    """Heures d'ouverture du salon ce jour."""
    hours = (business.business_hours if business else None) or _DEFAULT_HOURS
    win = _window(hours, day)
    if win is None:
        return None
    tz = business_tz(business)
    start, end = _local(day, win[0], tz), _local(day, win[1], tz)
    return (start, end) if end > start else None


def _staff_bounds(
    business: Business | None, member: Staff, day: date
) -> tuple[datetime, datetime] | None:
    """Heures du coiffeur, dans celles du salon."""
    salon = _salon_bounds(business, day)
    if salon is None:
        return None
    wh = member.working_hours
    # rien de saisi = horaires du salon
    if not isinstance(wh, dict) or _DAY_KEYS[day.weekday()] not in wh:
        return salon
    win = _window(wh, day)
    if win is None:
        return None  # jour off
    tz = business_tz(business)
    start = max(_local(day, win[0], tz), salon[0])
    end = min(_local(day, win[1], tz), salon[1])
    return (start, end) if end > start else None


def _peak(spans: list[tuple[datetime, datetime]]) -> int:
    """Nombre max de RDV en même temps."""
    points = [(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans]
    cur = best = 0
    for _, d in sorted(points, key=lambda p: (p[0], p[1])):
        cur += d
        best = max(best, cur)
    return best


async def _load_booked(
    db: AsyncSession,
    business_id: UUID,
    win_start: datetime,
    win_end: datetime,
    *,
    exclude_id: UUID | None = None,
) -> list[tuple[datetime, datetime, UUID | None, str]]:
    """RDV non annulés qui touchent la fenêtre."""
    filters = [
        Appointment.business_id == business_id,
        Appointment.status != "cancelled",
        Appointment.start_at < win_end,
        Appointment.end_at > win_start,
    ]
    if exclude_id is not None:
        filters.append(Appointment.id != exclude_id)
    rows = (
        await db.execute(
            select(
                Appointment.start_at, Appointment.end_at, Appointment.staff_id, Appointment.status
            ).where(*filters)
        )
    ).all()
    return [(_aware(bs), _aware(be), sid, st) for bs, be, sid, st in rows]


def _free_members(
    pool: StaffPool,
    business: Business | None,
    start: datetime,
    end: datetime,
    booked: list[tuple[datetime, datetime, UUID | None, str]],
    prestation_ids: Iterable[UUID] | None,
    only: UUID | None,
    cache: dict[tuple[UUID, date], tuple[datetime, datetime] | None],
    check_hours: bool = True,
) -> list[Staff]:
    """Coiffeurs libres et compétents sur [start, end)."""
    busy: set[UUID] = set()
    loose: list[tuple[datetime, datetime]] = []
    for bs, be, sid, status in booked:
        if not (start < be and end > bs):
            continue
        if sid is not None:
            # coiffeur en pause : n'occupe que lui
            busy.add(sid)
        elif status == "blocked":
            return []  # salon bloqué
        else:
            # sans coiffeur : un fauteuil pris
            loose.append((max(bs, start), min(be, end)))

    tz = business_tz(business)
    day = start.astimezone(tz).date()
    present: list[Staff] = []
    for m in pool.members:
        if m.id in busy:
            continue
        if not check_hours:
            # agenda : horaires ignorés
            present.append(m)
            continue
        key = (m.id, day)
        if key not in cache:
            cache[key] = _staff_bounds(business, m, day)
        bounds = cache[key]
        if bounds is not None and start >= bounds[0] and end <= bounds[1]:
            present.append(m)
    if len(present) - _peak(loose) < 1:
        return []
    out = [m for m in present if pool.can_do(m.id, prestation_ids)]
    if only is not None:
        out = [m for m in out if m.id == only]
    return out


def _grid(business: Business | None, day: date, duration_min: int) -> list[datetime]:
    """Départs toutes les 15 min (UTC)."""
    bounds = _salon_bounds(business, day)
    if bounds is None:
        return []
    cur, close = bounds
    step = timedelta(minutes=SLOT_STEP_MIN)
    dur = timedelta(minutes=duration_min)
    out: list[datetime] = []
    while cur + dur <= close:
        out.append(cur.astimezone(UTC))
        cur += step
    return out


def spread_slots(slots: list[datetime], duration_min: int) -> list[datetime]:
    """Espace les créneaux d'une durée (liste lisible)."""
    gap = timedelta(minutes=max(duration_min, SLOT_STEP_MIN))
    out: list[datetime] = []
    for s in slots:
        if not out or s >= out[-1] + gap:
            out.append(s)
    return out


# ── Jours / créneaux ─────────────────────────────────────────────────────────


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


async def _legacy_free_slots(
    db: AsyncSession,
    business_id: UUID,
    day: date,
    duration_min: int,
    *,
    business: Business | None = None,
) -> list[datetime]:
    """Un seul fauteuil : calcul historique."""
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


async def free_slots_with_staff(
    db: AsyncSession,
    business_id: UUID,
    day: date,
    duration_min: int = 30,
    *,
    business: Business | None = None,
    prestation_ids: Iterable[UUID] | None = None,
    staff_id: UUID | None = None,
    pool: StaffPool | None = None,
) -> list[tuple[datetime, list[Staff]]]:
    """Créneaux libres du jour + coiffeurs libres sur chacun."""
    from jenny.domain.models.business import Business as _Business

    if business is None:
        business = await db.get(_Business, business_id)
    if pool is None:
        pool = await load_staff_pool(db, business_id)
    if not pool.has_staff:
        slots = await _legacy_free_slots(db, business_id, day, duration_min, business=business)
        return [(s, []) for s in slots]

    if await is_day_closed(db, business_id, day, business=business):
        return []
    now = datetime.now(UTC)
    candidates = [s for s in _grid(business, day, duration_min) if s > now]
    if not candidates:
        return []
    dur = timedelta(minutes=duration_min)
    booked = await _load_booked(db, business_id, candidates[0], candidates[-1] + dur)
    ids = list(prestation_ids or [])
    cache: dict[tuple[UUID, date], tuple[datetime, datetime] | None] = {}
    out: list[tuple[datetime, list[Staff]]] = []
    for s in candidates:
        free = _free_members(pool, business, s, s + dur, booked, ids, staff_id, cache)
        if free:
            out.append((s, free))
    return out


async def free_slots_for_day(
    db: AsyncSession,
    business_id: UUID,
    day: date,
    duration_min: int = 30,
    *,
    business: Business | None = None,
    prestation_ids: Iterable[UUID] | None = None,
    staff_id: UUID | None = None,
    pool: StaffPool | None = None,
) -> list[datetime]:
    """Créneaux libres (début, UTC) d'un jour pour une durée donnée."""
    if pool is None:
        pool = await load_staff_pool(db, business_id)
    if not pool.has_staff:
        return await _legacy_free_slots(db, business_id, day, duration_min, business=business)
    pairs = await free_slots_with_staff(
        db,
        business_id,
        day,
        duration_min,
        business=business,
        prestation_ids=prestation_ids,
        staff_id=staff_id,
        pool=pool,
    )
    # grille fine, liste aérée
    return spread_slots([s for s, _ in pairs], duration_min)


async def next_free_slots(
    db: AsyncSession,
    business_id: UUID,
    duration_min: int = 30,
    *,
    from_day: date | None = None,
    max_days: int = 14,
    limit: int = 4,
    prestation_ids: Iterable[UUID] | None = None,
    staff_id: UUID | None = None,
) -> list[datetime]:
    """Premiers créneaux libres à partir d'un jour, en balayant les jours suivants."""
    from jenny.domain.models.business import Business as _Business

    business = await db.get(_Business, business_id)
    tz = business_tz(business)
    pool = await load_staff_pool(db, business_id)
    ids = list(prestation_ids or [])
    start = from_day or datetime.now(tz).date()
    found: list[datetime] = []
    for i in range(max_days):
        day = start + timedelta(days=i)
        slots = await free_slots_for_day(
            db,
            business_id,
            day,
            duration_min,
            business=business,
            prestation_ids=ids,
            staff_id=staff_id,
            pool=pool,
        )
        found.extend(slots)
        if len(found) >= limit:
            break
    return found[:limit]


async def find_free_staff(
    db: AsyncSession,
    business_id: UUID,
    start: datetime,
    end: datetime,
    *,
    business: Business | None = None,
    prestation_ids: Iterable[UUID] | None = None,
    staff_id: UUID | None = None,
    prefer_staff_id: UUID | None = None,
    exclude_appointment_id: UUID | None = None,
    pool: StaffPool | None = None,
    check_hours: bool = True,
) -> StaffPick:
    """Qui peut prendre [start, end) ? (staff_id impose, prefer tente)"""
    if pool is None:
        pool = await load_staff_pool(db, business_id)
    start, end = _aware(start), _aware(end)
    booked = await _load_booked(db, business_id, start, end, exclude_id=exclude_appointment_id)
    if not pool.has_staff:
        return StaffPick(free=not booked)
    if business is None:
        from jenny.domain.models.business import Business as _Business

        business = await db.get(_Business, business_id)
    free = _free_members(
        pool, business, start, end, booked, list(prestation_ids or []), staff_id, {}, check_hours
    )
    if not free:
        return StaffPick(free=False, has_staff=True)
    chosen = next((m for m in free if m.id == prefer_staff_id), free[0])
    return StaffPick(free=True, staff=chosen, has_staff=True)


async def staff_is_busy(
    db: AsyncSession,
    business_id: UUID,
    staff_id: UUID,
    start: datetime,
    end: datetime,
    *,
    exclude_appointment_id: UUID | None = None,
) -> bool:
    """Ce coiffeur a déjà un RDV ?"""
    start, end = _aware(start), _aware(end)
    booked = await _load_booked(db, business_id, start, end, exclude_id=exclude_appointment_id)
    return any(sid == staff_id and start < be and end > bs for bs, be, sid, _ in booked)


def format_slots_fr(slots: list[datetime], tz: ZoneInfo, *, with_day: bool = False) -> str:
    """Formate des créneaux pour Jenny : « 10h00, 14h00, 16h00 » (ou avec le jour)."""
    _days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    labels: list[str] = []
    for s in slots:
        loc = s.astimezone(tz)
        t = loc.strftime("%Hh%M")
        labels.append(f"{_days[loc.weekday()]} {loc.day:02d}/{loc.month:02d} à {t}" if with_day else t)
    return ", ".join(labels)
