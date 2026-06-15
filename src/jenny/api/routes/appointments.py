"""Rendez-vous / calendrier (onglet Calendrier façon Google Agenda).

CRUD scopé au business du JWT. Sert la vue calendrier du dashboard et peut être
alimenté par l'agent de planification de Jenny (création automatique de RDV).
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.customer import Customer
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/appointments", tags=["Appointments"])


class AppointmentItem(BaseModel):
    id: str
    title: str
    description: str | None = None
    location: str | None = None
    channel: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    customer_id: str | None = None
    customer_name: str | None = None
    conversation_id: str | None = None
    created_by: str | None = None
    # Acompte anti-no-show.
    deposit_cents: int | None = None
    deposit_status: str = "none"
    # Notes techniques internes (jamais montrées au client).
    staff_notes: str | None = None


class AppointmentListResponse(BaseModel):
    appointments: list[AppointmentItem]
    total: int


def _to_item(a: Appointment, customer_name: str | None) -> AppointmentItem:
    return AppointmentItem(
        id=str(a.id),
        title=a.title,
        description=a.description,
        location=a.location,
        channel=a.channel,
        start_at=a.start_at,
        end_at=a.end_at,
        status=a.status,
        customer_id=str(a.customer_id) if a.customer_id else None,
        customer_name=customer_name,
        conversation_id=str(a.conversation_id) if a.conversation_id else None,
        created_by=a.created_by,
        deposit_cents=a.deposit_cents,
        deposit_status=a.deposit_status,
        staff_notes=a.staff_notes,
    )


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    db: DbSession,
    principal: CurrentUser,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> AppointmentListResponse:
    """Liste les rendez-vous du business, optionnellement dans une fenêtre [start, end]."""
    bid = principal.business_id
    if bid is None:
        return AppointmentListResponse(appointments=[], total=0)
    filters = [Appointment.business_id == bid]
    if start is not None:
        filters.append(Appointment.end_at >= start)
    if end is not None:
        filters.append(Appointment.start_at <= end)
    rows = (
        await db.execute(
            select(Appointment, Customer.full_name)
            .outerjoin(Customer, Appointment.customer_id == Customer.id)
            .where(*filters)
            .order_by(Appointment.start_at.asc())
            .limit(limit)
        )
    ).all()
    items = [_to_item(a, name) for a, name in rows]
    return AppointmentListResponse(appointments=items, total=len(items))


class AppointmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    channel: str | None = Field(default="manual", max_length=50)
    customer_id: UUID | None = None
    conversation_id: UUID | None = None


@router.post("", response_model=AppointmentItem, status_code=201)
async def create_appointment(
    body: AppointmentCreate, db: DbSession, principal: CurrentUser
) -> AppointmentItem:
    """Crée un rendez-vous pour le business courant."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    if body.end_at < body.start_at:
        raise HTTPException(400, "La fin doit être postérieure au début")
    appt = Appointment(
        business_id=bid,
        title=body.title.strip(),
        description=body.description,
        location=body.location,
        channel=body.channel or "manual",
        start_at=body.start_at,
        end_at=body.end_at,
        customer_id=body.customer_id,
        conversation_id=body.conversation_id,
        status="scheduled",
        created_by=principal.email or "Agent",
    )
    db.add(appt)
    await db.flush()
    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "Agent",
        action="appointment.created",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"RDV « {appt.title} » créé le {appt.start_at:%d/%m %H:%M}",
    )
    await db.commit()
    await db.refresh(appt)
    customer_name = None
    if appt.customer_id:
        customer_name = await db.scalar(
            select(Customer.full_name).where(Customer.id == appt.customer_id)
        )
    logger.info("appointment.created", business_id=str(bid), appt_id=str(appt.id))
    return _to_item(appt, customer_name)


class AppointmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    status: Literal["scheduled", "confirmed", "cancelled", "completed", "no_show"] | None = None
    staff_notes: str | None = Field(default=None, max_length=5000)


@router.patch("/{appointment_id}", response_model=AppointmentItem)
async def update_appointment(
    appointment_id: UUID, body: AppointmentUpdate, db: DbSession, principal: CurrentUser
) -> AppointmentItem:
    """Met à jour un rendez-vous (horaires, statut, détails)."""
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.business_id != principal.business_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    data = body.model_dump(exclude_unset=True)
    for f in ("title", "description", "location", "status", "start_at", "end_at", "staff_notes"):
        if f in data and data[f] is not None:
            setattr(appt, f, data[f])
    if appt.end_at < appt.start_at:
        raise HTTPException(400, "La fin doit être postérieure au début")
    record_audit(
        db,
        business_id=appt.business_id,
        actor=principal.email or "Agent",
        action="appointment.updated",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"RDV « {appt.title} » mis à jour ({appt.status})",
    )
    await db.commit()
    await db.refresh(appt)
    customer_name = None
    if appt.customer_id:
        customer_name = await db.scalar(
            select(Customer.full_name).where(Customer.id == appt.customer_id)
        )
    return _to_item(appt, customer_name)


@router.post("/{appointment_id}/deposit/mark-paid", response_model=AppointmentItem)
async def mark_deposit_paid(
    appointment_id: UUID, db: DbSession, principal: CurrentUser
) -> AppointmentItem:
    """Enregistre l'acompte comme reçu (paiement sur place / hors Stripe).

    Passe l'acompte à « paid », le ``PaymentRecord`` à « paid » et confirme le RDV.
    Utile quand le salon encaisse lui-même (espèces, TPE) sans passer par le lien.
    """
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.business_id != principal.business_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    if appt.deposit_status == "none" or appt.deposit_cents is None:
        raise HTTPException(400, "Aucun acompte demandé pour ce rendez-vous")

    appt.deposit_status = "paid"
    if appt.status == "scheduled":
        appt.status = "confirmed"
    if appt.deposit_payment_id is not None:
        from jenny.domain.models.payment_record import PaymentRecord

        payment = await db.get(PaymentRecord, appt.deposit_payment_id)
        if payment is not None:
            payment.status = "paid"
    record_audit(
        db,
        business_id=appt.business_id,
        actor=principal.email or "Agent",
        action="appointment.deposit_paid",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"Acompte encaissé pour « {appt.title} »",
    )
    await db.commit()
    await db.refresh(appt)
    customer_name = None
    if appt.customer_id:
        customer_name = await db.scalar(
            select(Customer.full_name).where(Customer.id == appt.customer_id)
        )
    logger.info("appointment.deposit_paid", business_id=str(appt.business_id), appt_id=str(appt.id))
    return _to_item(appt, customer_name)


@router.delete("/{appointment_id}")
async def delete_appointment(
    appointment_id: UUID, db: DbSession, principal: CurrentUser
) -> dict:
    """Supprime un rendez-vous."""
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.business_id != principal.business_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    title = appt.title
    record_audit(
        db,
        business_id=appt.business_id,
        actor=principal.email or "Agent",
        action="appointment.deleted",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"RDV « {title} » supprimé",
    )
    await db.delete(appt)
    await db.commit()
    return {"status": "deleted", "id": str(appointment_id)}


# ── Export iCalendar (.ics) ──────────────────────────────────────────────────


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_dt(dt: datetime) -> str:
    d = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


_ICS_STATUS = {
    "confirmed": "CONFIRMED",
    "scheduled": "TENTATIVE",
    "cancelled": "CANCELLED",
    "completed": "CONFIRMED",
}


@router.get("/export.ics")
async def export_ics(db: DbSession, principal: CurrentUser) -> Response:
    """Exporte les rendez-vous du business au format iCalendar (.ics).

    Importable dans Google Agenda, Apple Calendrier, Outlook… sans intégration
    OAuth : un vrai standard interopérable.
    """
    bid = principal.business_id
    rows: list[Appointment] = []
    if bid is not None:
        rows = list(
            (
                await db.execute(
                    select(Appointment)
                    .where(Appointment.business_id == bid)
                    .order_by(Appointment.start_at.asc())
                    .limit(2000)
                )
            ).scalars().all()
        )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jenny//Agenda//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Jenny — Rendez-vous",
    ]
    for a in rows:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{a.id}@jenny.ai",
            f"DTSTAMP:{_ics_dt(a.created_at)}",
            f"DTSTART:{_ics_dt(a.start_at)}",
            f"DTEND:{_ics_dt(a.end_at)}",
            f"SUMMARY:{_ics_escape(a.title)}",
            f"STATUS:{_ICS_STATUS.get(a.status, 'TENTATIVE')}",
        ]
        if a.description:
            lines.append(f"DESCRIPTION:{_ics_escape(a.description)}")
        if a.location:
            lines.append(f"LOCATION:{_ics_escape(a.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines) + "\r\n"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=jenny-agenda.ics"},
    )
