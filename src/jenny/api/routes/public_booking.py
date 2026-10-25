"""Réservation publique en ligne (page /book/[slug]).

Endpoints **non authentifiés** permettant à un client final de prendre un
rendez-vous depuis une page publique, façon Calendly :

- ``GET  /public/booking/{slug}``         → infos publiques du business
- ``GET  /public/booking/{slug}/slots``   → créneaux disponibles d'un jour
- ``POST /public/booking/{slug}/book``    → confirme un créneau (crée le RDV)

Les créneaux sont calculés à partir des horaires d'ouverture (``business_hours``)
dans le fuseau du business, en retirant les créneaux déjà réservés et les
créneaux passés. La réservation crée un vrai ``Customer`` (dédupliqué par email)
et un vrai ``Appointment`` (statut ``scheduled``), et notifie l'équipe.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, select

from jenny.api.dependencies import DbSession
from jenny.core.logging import get_logger
from jenny.db.conflicts import is_slot_taken
from jenny.notifications.outbound import notify_customer
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.services.audit_service import record_audit

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
_MAX_DURATION = 240
_MAX_DAYS_AHEAD = 120


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


# ── Infos publiques ──────────────────────────────────────────────────────────


class BookingBusinessInfo(BaseModel):
    name: str
    slug: str
    description: str | None = None
    timezone: str
    business_hours: dict | None = None


@router.get("/{slug}", response_model=BookingBusinessInfo)
async def booking_info(slug: str, db: DbSession) -> BookingBusinessInfo:
    """Infos publiques affichées sur la page de réservation (aucune donnée sensible)."""
    b = await _load_active_business(db, slug)
    return BookingBusinessInfo(
        name=b.name,
        slug=b.slug,
        description=b.description,
        timezone=b.timezone or "Europe/Paris",
        business_hours=b.business_hours or _DEFAULT_HOURS,
    )


# ── Créneaux disponibles ─────────────────────────────────────────────────────


class BookingSlot(BaseModel):
    start_at: datetime
    end_at: datetime
    label: str  # HH:MM dans le fuseau du business


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
    duration: Annotated[int, Query(ge=_MIN_DURATION, le=_MAX_DURATION)] = 30,
) -> BookingSlotsResponse:
    """Créneaux libres d'un jour donné (horaires - réservations - créneaux passés)."""
    b = await _load_active_business(db, slug)
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Date invalide (attendu AAAA-MM-JJ)") from None

    tz = _business_tz(b)
    today_local = datetime.now(tz).date()
    if day < today_local or day > today_local + timedelta(days=_MAX_DAYS_AHEAD):
        return BookingSlotsResponse(
            date=date_str, timezone=str(tz), duration_minutes=duration, slots=[]
        )

    step = timedelta(minutes=duration)
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
    duration: int = Field(default=30, ge=_MIN_DURATION, le=_MAX_DURATION)
    notes: str | None = Field(default=None, max_length=2000)


class BookingConfirmation(BaseModel):
    id: str
    status: str
    business_name: str
    start_at: datetime
    end_at: datetime
    message: str


@router.post("/{slug}/book", response_model=BookingConfirmation, status_code=201)
async def booking_book(slug: str, body: BookingRequest, db: DbSession) -> BookingConfirmation:
    """Confirme une réservation : crée le client (dédupliqué) et le rendez-vous."""
    b = await _load_active_business(db, slug)

    start = body.start_at if body.start_at.tzinfo else body.start_at.replace(tzinfo=UTC)
    start = start.astimezone(UTC)
    end = start + timedelta(minutes=body.duration)
    if start <= datetime.now(UTC):
        raise HTTPException(400, "Ce créneau est déjà passé, choisissez-en un autre")

    # Anti double-réservation : refuse si un RDV non annulé chevauche le créneau.
    clash = (
        await db.execute(
            select(Appointment.id).where(
                Appointment.business_id == b.id,
                Appointment.status != "cancelled",
                and_(Appointment.start_at < end, Appointment.end_at > start),
            )
        )
    ).first()
    if clash is not None:
        raise HTTPException(409, "Ce créneau vient d'être réservé, choisissez-en un autre")

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

    title = f"RDV — {body.full_name.strip()}"
    appt = Appointment(
        business_id=b.id,
        customer_id=customer.id,
        title=title,
        description=body.notes or None,
        channel="booking",
        start_at=start,
        end_at=end,
        status="scheduled",
        created_by=f"{body.full_name.strip()} (réservation en ligne)",
    )
    db.add(appt)
    await db.flush()

    tz = _business_tz(b)
    when_local = start.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
    db.add(
        Notification(
            business_id=b.id,
            recipient=None,
            kind="booking",
            title="Nouvelle réservation en ligne",
            body=f"{body.full_name.strip()} a réservé le {when_local}.",
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
        raise HTTPException(409, "Ce créneau vient d'être réservé, choisissez-en un autre") from exc
    await db.refresh(appt)
    logger.info(
        "public.booking.created",
        business_id=str(b.id),
        appt_id=str(appt.id),
        customer_id=str(customer.id),
    )
    # confirmation AU CLIENT : avant, il ne recevait rien du tout
    await notify_customer(
        db,
        business_id=b.id,
        customer_id=customer.id,
        text=(
            f"Votre rendez-vous est confirmé : {title}, le {when_local}. "
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
            f"Votre rendez-vous du {when_local} est bien enregistré. "
            f"L'équipe de {b.name} vous confirmera rapidement."
        ),
    )
