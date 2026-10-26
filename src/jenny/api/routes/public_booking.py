"""Réservation publique en ligne (page /book/[slug]).

Endpoints **non authentifiés** permettant à un client final de prendre un
rendez-vous depuis une page publique, façon Calendly :

- ``GET  /public/booking/{slug}``         → infos publiques du business
- ``GET  /public/booking/{slug}/slots``   → créneaux disponibles d'un jour
- ``POST /public/booking/{slug}/book``    → confirme un créneau (crée le RDV)

Avec des coiffeurs : choix possible (``staff_id``), sinon attribution auto.
Prestation au choix (``prestation_id``) : durée du catalogue et compétences.

Les créneaux sont calculés à partir des horaires d'ouverture (``business_hours``)
dans le fuseau du business, en retirant les créneaux déjà réservés et les
créneaux passés. La réservation crée un vrai ``Customer`` (dédupliqué par email)
et un vrai ``Appointment`` (statut ``scheduled``), et notifie l'équipe.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.dependencies import DbSession
from jenny.core.events import publish_notification_event
from jenny.core.logging import get_logger
from jenny.db.conflicts import is_slot_taken
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff
from jenny.notifications.outbound import notify_customer
from jenny.services.audit_service import record_audit
from jenny.services.availability import (
    MAX_SERVICE_MINUTES,
    StaffPool,
    find_free_staff,
    free_slots_with_staff,
    is_day_closed,
    load_staff_pool,
    service_minutes,
)
from jenny.services.prestation_service import load_active_prestations

logger = get_logger(__name__)

router = APIRouter(prefix="/public/booking", tags=["Public booking"])

# Lundi=0 … Dimanche=6 (aligné sur ``date.weekday()``).
_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Horaires par défaut si le business n'en a pas configuré : lun-ven 9h-18h.
_DEFAULT_HOURS: dict[str, list[str] | None] = {
    "mon": ["09:00", "18:00"],
    "tue": ["09:00", "18:00"],
    "wed": ["09:00", "18:00"],
    "thu": ["09:00", "18:00"],
    "fri": ["09:00", "18:00"],
    "sat": None,
    "sun": None,
}

_MIN_DURATION = 15
# durée libre, sans prestation
_MAX_DURATION = 240
_MAX_DAYS_AHEAD = 120
_TOO_LONG = "Cette prestation est trop longue pour la réservation en ligne, appelez le salon"
_FREE_TOO_LONG = f"Sans prestation, {_MAX_DURATION} minutes au maximum"

def _business_tz(b: Business) -> ZoneInfo:
    try:
        return ZoneInfo(b.timezone or "Europe/Paris")
    except Exception:
        return ZoneInfo("Europe/Paris")


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        h, m = value.split(":")
        hi, mi = int(h), int(m)
        if 0 <= hi <= 23 and 0 <= mi <= 59:
            return hi, mi
    except (ValueError, AttributeError):
        pass
    return None


def _day_slots(b: Business, day: date, duration_min: int) -> list[datetime]:
    """Créneaux candidats (début, en UTC) pour un jour, hors réservations."""
    tz = _business_tz(b)
    hours = b.business_hours or _DEFAULT_HOURS
    window = hours.get(_DAY_KEYS[day.weekday()])
    if not window or len(window) != 2:
        return []
    open_hm = _parse_hhmm(window[0])
    close_hm = _parse_hhmm(window[1])
    if open_hm is None or close_hm is None:
        return []
    start_local = datetime(day.year, day.month, day.day, open_hm[0], open_hm[1], tzinfo=tz)
    close_local = datetime(day.year, day.month, day.day, close_hm[0], close_hm[1], tzinfo=tz)
    if close_local <= start_local:
        return []
    step = timedelta(minutes=duration_min)
    out: list[datetime] = []
    cur = start_local
    while cur + step <= close_local:
        out.append(cur.astimezone(UTC))
        cur += step
    return out


async def _load_active_business(db, slug: str) -> Business:
    b = (
        await db.execute(select(Business).where(Business.slug == slug))
    ).scalar_one_or_none()
    if b is None or not b.is_active:
        raise HTTPException(404, "Page de réservation introuvable")
    return b


def _check_staff_choice(pool: StaffPool, staff_id: UUID | None) -> None:
    """Le coiffeur choisi doit être actif."""
    if staff_id is not None and pool.has_staff and pool.get(staff_id) is None:
        raise HTTPException(400, "Ce coiffeur n'est plus disponible, rechargez la page")


async def _load_prestation(
    db: AsyncSession, b: Business, prestation_id: UUID | None
) -> Prestation | None:
    """Prestation active du salon."""
    if prestation_id is None:
        return None
    p = await db.get(Prestation, prestation_id)
    if p is None or p.business_id != b.id or not p.is_active:
        raise HTTPException(400, "Cette prestation n'est plus proposée, rechargez la page")
    return p


def _duration_of(p: Prestation | None, fallback: int) -> int:
    """Vraie durée du catalogue, comme le chat."""
    if p is None:
        return fallback
    return service_minutes(p.duration_minutes, fallback)


def _booking_minutes(p: Prestation | None, asked: int) -> int:
    """Durée réservée, ou 400."""
    if p is None:
        if asked > _MAX_DURATION:
            raise HTTPException(400, _FREE_TOO_LONG)
        return asked
    minutes = _duration_of(p, 30)
    if minutes > MAX_SERVICE_MINUTES:
        # jamais coupée : refusée
        raise HTTPException(400, _TOO_LONG)
    return minutes


def _in_opening(b: Business, start: datetime, end: datetime) -> bool:
    """Dans les horaires du jour ?"""
    tz = _business_tz(b)
    day = start.astimezone(tz).date()
    window = (b.business_hours or _DEFAULT_HOURS).get(_DAY_KEYS[day.weekday()])
    if not window or len(window) != 2:
        return False
    a, z = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    if a is None or z is None:
        return False
    opens = datetime(day.year, day.month, day.day, a[0], a[1], tzinfo=tz)
    closes = datetime(day.year, day.month, day.day, z[0], z[1], tzinfo=tz)
    return opens <= start and end <= closes


# ── Infos publiques ──────────────────────────────────────────────────────────


class BookingStaff(BaseModel):
    id: str
    display_name: str
    # null = sait tout faire
    prestation_ids: list[str] | None = None


class BookingPrestation(BaseModel):
    id: str
    name: str
    category: str
    duration_minutes: int
    # null = prix sur demande
    price_cents: int | None = None


class BookingBusinessInfo(BaseModel):
    name: str
    slug: str
    description: str | None = None
    timezone: str
    business_hours: dict | None = None
    phone: str | None = None
    # coiffeurs au choix (vide = salon solo)
    staff: list[BookingStaff] = []
    # catalogue actif
    prestations: list[BookingPrestation] = []


def _public_staff(pool: StaffPool, m: Staff) -> BookingStaff:
    """Coiffeur vu du client."""
    known = pool.skills.get(m.id) or set()
    open_all = not known and m.all_services
    return BookingStaff(
        id=str(m.id),
        display_name=m.display_name,
        prestation_ids=None if open_all else sorted(str(p) for p in known),
    )


@router.get("/{slug}", response_model=BookingBusinessInfo)
async def booking_info(slug: str, db: DbSession) -> BookingBusinessInfo:
    """Infos publiques affichées sur la page de réservation (aucune donnée sensible)."""
    b = await _load_active_business(db, slug)
    pool = await load_staff_pool(db, b.id)
    prestations = await load_active_prestations(db, b.id)
    return BookingBusinessInfo(
        name=b.name,
        slug=b.slug,
        description=b.description,
        timezone=b.timezone or "Europe/Paris",
        business_hours=b.business_hours or _DEFAULT_HOURS,
        phone=(b.phone or "").strip() or None,
        staff=[_public_staff(pool, m) for m in pool.members],
        prestations=[
            BookingPrestation(
                id=str(p.id),
                name=p.name,
                category=p.category,
                duration_minutes=_duration_of(p, 30),
                price_cents=p.price_cents or None,
            )
            for p in prestations
        ],
    )


# ── Créneaux disponibles ─────────────────────────────────────────────────────


class BookingSlot(BaseModel):
    start_at: datetime
    end_at: datetime
    label: str  # HH:MM dans le fuseau du business
    # coiffeurs libres sur ce créneau
    staff_ids: list[str] = []


class BookingSlotsResponse(BaseModel):
    date: str
    timezone: str
    duration_minutes: int
    slots: list[BookingSlot]


@router.get("/{slug}/slots", response_model=BookingSlotsResponse)
async def booking_slots(
    slug: str,
    db: DbSession,
    date_str: Annotated[str, Query(alias="date", description="Jour AAAA-MM-JJ")],
    duration: Annotated[int, Query(ge=_MIN_DURATION, le=MAX_SERVICE_MINUTES)] = 30,
    staff_id: Annotated[UUID | None, Query(description="Coiffeur choisi")] = None,
    prestation_id: Annotated[UUID | None, Query(description="Prestation choisie")] = None,
) -> BookingSlotsResponse:
    """Créneaux libres d'un jour donné (horaires - réservations - créneaux passés)."""
    b = await _load_active_business(db, slug)
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Date invalide (attendu AAAA-MM-JJ)") from None
    presta = await _load_prestation(db, b, prestation_id)
    # la prestation fixe la durée
    duration = _booking_minutes(presta, duration)

    tz = _business_tz(b)
    today_local = datetime.now(tz).date()
    if day < today_local or day > today_local + timedelta(days=_MAX_DAYS_AHEAD):
        return BookingSlotsResponse(
            date=date_str, timezone=str(tz), duration_minutes=duration, slots=[]
        )

    step = timedelta(minutes=duration)
    # salon avec coiffeurs : calcul par fauteuil
    pool = await load_staff_pool(db, b.id)
    if pool.has_staff:
        _check_staff_choice(pool, staff_id)
        pairs = await free_slots_with_staff(
            db,
            b.id,
            day,
            duration,
            business=b,
            prestation_ids=[presta.id] if presta else None,
            staff_id=staff_id,
            pool=pool,
        )
        return BookingSlotsResponse(
            date=date_str,
            timezone=str(tz),
            duration_minutes=duration,
            slots=[
                BookingSlot(
                    start_at=s,
                    end_at=s + step,
                    label=s.astimezone(tz).strftime("%H:%M"),
                    staff_ids=[str(m.id) for m in free],
                )
                for s, free in pairs
            ],
        )

    candidates = _day_slots(b, day, duration)
    now_utc = datetime.now(UTC)
    candidates = [s for s in candidates if s > now_utc]
    if not candidates:
        return BookingSlotsResponse(
            date=date_str, timezone=str(tz), duration_minutes=duration, slots=[]
        )

    # Réservations existantes chevauchant la journée (hors annulées).
    win_start = candidates[0]
    win_end = candidates[-1] + step
    booked = (
        await db.execute(
            select(Appointment.start_at, Appointment.end_at).where(
                Appointment.business_id == b.id,
                Appointment.status != "cancelled",
                Appointment.start_at < win_end,
                Appointment.end_at > win_start,
            )
        )
    ).all()

    def _taken(slot_start: datetime) -> bool:
        slot_end = slot_start + step
        for bs, be in booked:
            bs_u = bs if bs.tzinfo else bs.replace(tzinfo=UTC)
            be_u = be if be.tzinfo else be.replace(tzinfo=UTC)
            if slot_start < be_u and slot_end > bs_u:
                return True
        return False

    slots = [
        BookingSlot(start_at=s, end_at=s + step, label=s.astimezone(tz).strftime("%H:%M"))
        for s in candidates
        if not _taken(s)
    ]
    return BookingSlotsResponse(
        date=date_str, timezone=str(tz), duration_minutes=duration, slots=slots
    )


# ── Confirmation d'un créneau ────────────────────────────────────────────────


class BookingRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    start_at: datetime
    # prestation : durée du catalogue
    duration: int = Field(default=30, ge=_MIN_DURATION, le=MAX_SERVICE_MINUTES)
    notes: str | None = Field(default=None, max_length=2000)
    # sans choix : premier coiffeur libre
    staff_id: UUID | None = None
    # durée et compétences du catalogue
    prestation_id: UUID | None = None


class BookingConfirmation(BaseModel):
    id: str
    status: str
    business_name: str
    start_at: datetime
    end_at: datetime
    message: str
    staff_id: str | None = None
    staff_name: str | None = None
    prestation_name: str | None = None


_TAKEN = "Ce créneau vient d'être réservé, choisissez-en un autre"


@router.post("/{slug}/book", response_model=BookingConfirmation, status_code=201)
async def booking_book(slug: str, body: BookingRequest, db: DbSession) -> BookingConfirmation:
    """Confirme une réservation : crée le client (dédupliqué) et le rendez-vous."""
    b = await _load_active_business(db, slug)
    presta = await _load_prestation(db, b, body.prestation_id)
    skills = [presta.id] if presta else None

    start = body.start_at if body.start_at.tzinfo else body.start_at.replace(tzinfo=UTC)
    start = start.astimezone(UTC)
    end = start + timedelta(minutes=_booking_minutes(presta, body.duration))
    if start <= datetime.now(UTC):
        raise HTTPException(400, "Ce créneau est déjà passé, choisissez-en un autre")

    tz = _business_tz(b)
    pool = await load_staff_pool(db, b.id)
    _check_staff_choice(pool, body.staff_id)
    if await is_day_closed(db, b.id, start.astimezone(tz).date(), business=b):
        raise HTTPException(400, "Le salon est fermé ce jour-là, choisissez un autre jour")
    # solo : horaires du salon
    if not pool.has_staff and not _in_opening(b, start, end):
        raise HTTPException(400, "Ce créneau est hors des horaires du salon, choisissez-en un autre")

    async def _pick() -> Staff | None:
        """Par coiffeur s'il y en a, sinon tout le salon."""
        pick = await find_free_staff(
            db, b.id, start, end, business=b, prestation_ids=skills, staff_id=body.staff_id, pool=pool
        )
        if not pick.free:
            raise HTTPException(409, _TAKEN)
        return pick.staff

    chosen = await _pick()

    # Client dédupliqué par email au sein du business.
    email = body.email.strip().lower()
    customer = (
        await db.execute(
            select(Customer).where(Customer.business_id == b.id, Customer.email == email)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if customer is None:
        customer = Customer(
            business_id=b.id,
            full_name=body.full_name.strip(),
            email=email,
            phone=(body.phone or None),
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(customer)
        await db.flush()
    else:
        customer.last_seen_at = now
        if not customer.full_name:
            customer.full_name = body.full_name.strip()
        if not customer.phone and body.phone:
            customer.phone = body.phone

    # titre = prestation, comme le chat
    title = presta.name if presta else f"RDV — {body.full_name.strip()}"

    async def _insert(staff: Staff | None) -> Appointment:
        """RDV posé dans un savepoint."""
        row = Appointment(
            business_id=b.id,
            customer_id=customer.id,
            staff_id=staff.id if staff else None,
            title=title,
            description=body.notes or None,
            channel="booking",
            start_at=start,
            end_at=end,
            status="scheduled",
            created_by=f"{body.full_name.strip()} (réservation en ligne)",
        )
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row

    try:
        appt = await _insert(chosen)
    except Exception as exc:  # course : la base tranche
        if not is_slot_taken(exc):
            raise
        # auto : un autre coiffeur libre ?
        if body.staff_id is not None or not pool.has_staff:
            raise HTTPException(409, _TAKEN) from exc
        chosen = await _pick()
        try:
            appt = await _insert(chosen)
        except Exception as again:
            if not is_slot_taken(again):
                raise
            raise HTTPException(409, _TAKEN) from again
    staff_id = chosen.id if chosen else None
    staff_name = chosen.display_name if chosen else None
    with_staff = f" avec {staff_name}" if staff_name else ""

    when_local = start.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
    db.add(
        Notification(
            business_id=b.id,
            recipient=None,
            kind="booking",
            title="Nouvelle réservation en ligne",
            body=(
                f"{body.full_name.strip()} a réservé"
                f"{f' « {presta.name} »' if presta else ''} le {when_local}{with_staff}."
            ),
            meta={"appointment_id": str(appt.id), "customer_id": str(customer.id)},
        )
    )
    record_audit(
        db,
        business_id=b.id,
        actor=email,
        action="appointment.booked_online",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"Réservation en ligne « {title} » le {when_local}",
    )
    try:
        await db.commit()
    except Exception as exc:  # créneau pris entre-temps (course)
        if not is_slot_taken(exc):
            raise
        await db.rollback()
        raise HTTPException(409, _TAKEN) from exc
    await db.refresh(appt)
    logger.info(
        "public.booking.created",
        business_id=str(b.id),
        appt_id=str(appt.id),
        customer_id=str(customer.id),
    )
    # cloche + agenda en direct
    publish_notification_event(b.id, kind="booking", title="Nouvelle réservation en ligne")
    # confirmation AU CLIENT : avant, il ne recevait rien du tout
    await notify_customer(
        db,
        business_id=b.id,
        customer_id=customer.id,
        text=(
            f"Votre rendez-vous est confirmé : {title}, le {when_local}{with_staff}. "
            f"À très vite chez {b.name} ! Pour modifier ou annuler, répondez à ce message."
        ),
        subject=f"Rendez-vous confirmé — {b.name}",
    )

    return BookingConfirmation(
        id=str(appt.id),
        status=appt.status,
        business_name=b.name,
        start_at=appt.start_at,
        end_at=appt.end_at,
        message=(
            f"Votre rendez-vous du {when_local}{with_staff} est bien enregistré. "
            f"L'équipe de {b.name} vous confirmera rapidement."
        ),
        staff_id=str(staff_id) if staff_id else None,
        staff_name=staff_name,
        prestation_name=presta.name if presta else None,
    )
