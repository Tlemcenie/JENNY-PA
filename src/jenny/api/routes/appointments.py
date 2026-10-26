"""Rendez-vous / calendrier (onglet Calendrier façon Google Agenda).

CRUD scopé au business du JWT. Sert la vue calendrier du dashboard et peut être
alimenté par l'agent de planification de Jenny (création automatique de RDV).
"""

import contextlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.db.conflicts import is_slot_taken
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff
from jenny.services.audit_service import record_audit
from jenny.services.availability import (
    StaffPick,
    business_tz,
    find_free_staff,
    freed_is_bookable,
    load_staff_pool,
    staff_is_busy,
)

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
    # coiffeur du RDV
    staff_id: str | None = None
    staff_name: str | None = None
    staff_color: str | None = None


class AppointmentListResponse(BaseModel):
    appointments: list[AppointmentItem]
    total: int


def _to_item(
    a: Appointment,
    customer_name: str | None,
    staff_name: str | None = None,
    staff_color: str | None = None,
) -> AppointmentItem:
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
        staff_id=str(a.staff_id) if a.staff_id else None,
        staff_name=staff_name,
        staff_color=staff_color,
    )


async def _item(db: AsyncSession, a: Appointment) -> AppointmentItem:
    """Item avec client et coiffeur."""
    customer_name = None
    if a.customer_id:
        customer_name = await db.scalar(
            select(Customer.full_name).where(Customer.id == a.customer_id)
        )
    staff_name = staff_color = None
    if a.staff_id:
        row = (
            await db.execute(select(Staff.display_name, Staff.color).where(Staff.id == a.staff_id))
        ).first()
        if row is not None:
            staff_name, staff_color = row
    return _to_item(a, customer_name, staff_name, staff_color)


async def _check_staff(db: AsyncSession, bid: UUID, staff_id: UUID | None) -> None:
    """Le coiffeur doit être du salon."""
    if staff_id is None:
        return
    owner = await db.scalar(select(Staff.business_id).where(Staff.id == staff_id))
    if owner != bid:
        raise HTTPException(400, "Coiffeur inconnu pour ce salon")


_OVERLAP = "Ce créneau chevauche un rendez-vous existant"
_NO_STAFF = "Aucun coiffeur libre sur ce créneau"
_NO_SKILL = "Aucun coiffeur libre ne fait cette prestation sur ce créneau"
_WD = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _utc(dt: datetime) -> datetime:
    """SQLite rend du naïf."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _ensure_room(
    db: AsyncSession,
    bid: UUID,
    start: datetime,
    end: datetime,
    *,
    staff_id: UUID | None,
    auto: bool = False,
    exclude_id: UUID | None = None,
    prestation_ids: list[UUID] | None = None,
) -> UUID | None:
    """Vérifie qu'un fauteuil reste libre."""
    pool = await load_staff_pool(db, bid)

    async def _pick(only: UUID | None, hours: bool, skills: list[UUID] | None) -> StaffPick:
        return await find_free_staff(
            db,
            bid,
            start,
            end,
            staff_id=only,
            prestation_ids=skills,
            pool=pool,
            exclude_appointment_id=exclude_id,
            check_hours=hours,
        )

    if auto and staff_id is None:
        # présent d'abord, sinon hors horaires
        pick = await _pick(None, True, prestation_ids)
        if not pick.free and pool.has_staff:
            pick = await _pick(None, False, prestation_ids)
        if not pick.free:
            # libre mais pas compétent ?
            if prestation_ids and pool.has_staff and (await _pick(None, False, None)).free:
                raise HTTPException(409, _NO_SKILL)
            raise HTTPException(409, _NO_STAFF)
        return pick.staff.id if pick.staff else None
    if staff_id is not None and pool.has_staff and pool.get(staff_id) is None:
        # coiffeur en pause : lui seul
        if await staff_is_busy(
            db, bid, staff_id, start, end, exclude_appointment_id=exclude_id, salon_blocks=True
        ):
            raise HTTPException(409, _OVERLAP)
        return staff_id
    if not (await _pick(staff_id, False, None)).free:
        raise HTTPException(409, _OVERLAP)
    return staff_id


async def _prestations_for(
    db: AsyncSession, bid: UUID, prestation_id: UUID | None, title: str
) -> list[UUID]:
    """Prestation choisie, ou titre exact."""
    if prestation_id is not None:
        owner = await db.scalar(select(Prestation.business_id).where(Prestation.id == prestation_id))
        if owner != bid:
            raise HTTPException(400, "Prestation inconnue pour ce salon")
        return [prestation_id]
    from jenny.services.prestation_service import (
        _MULTI_SPLIT_RE,
        _norm,
        load_active_prestations,
    )

    # titre = nom exact, sinon rien
    parts = [_norm(x) for x in _MULTI_SPLIT_RE.split(title or "") if x and x.strip()]
    if not parts:
        return []
    by_name = {_norm(p.name): p.id for p in await load_active_prestations(db, bid)}
    ids = [by_name.get(x) for x in parts]
    if any(i is None for i in ids):
        return []
    return list(dict.fromkeys(i for i in ids if i is not None))


async def _after_free(db: AsyncSession, freed: dict[str, Any]) -> bool:
    """Place libérée : liste d'attente + relances."""
    from jenny.services import gap_filler
    from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

    bid = freed["business_id"]
    start = _utc(freed["start_at"])
    try:
        # coiffeur en pause : rien de libre
        if not await freed_is_bookable(
            db, bid, start, _utc(freed["end_at"]), staff_id=freed["staff_id"]
        ):
            await db.rollback()
            logger.info("appointment.freed_not_bookable", business_id=str(bid))
            return False
        tz = business_tz(await db.get(Business, bid))
        cur = start.astimezone(tz)
        when = f"{_WD[cur.weekday()]} {cur.day:02d}/{cur.month:02d} à {cur.strftime('%Hh%M')}"
        # créneau exact, perdu au commit
        await notify_waitlist_for_freed_slot(
            db,
            business_id=bid,
            service=freed["service"],
            when_label=when,
            slot_start=start,
            duration_minutes=freed["minutes"],
            staff_id=freed["staff_id"],
        )
        await db.commit()
    except Exception as exc:  # jamais bloquant
        logger.warning("appointment.freed_hook_failed", business_id=str(bid), error=str(exc))
        with contextlib.suppress(Exception):
            await db.rollback()
    try:
        # passe agenda, même si raté
        return await gap_filler.schedule_after_change(db, bid)
    except Exception as exc:  # jamais bloquant
        logger.warning("appointment.gap_pass_failed", business_id=str(bid), error=str(exc))
        return False


def _frees_slot(a: Appointment) -> bool:
    """RDV à venir encore actif ?"""
    if a.status in ("cancelled", "completed", "no_show"):
        return False
    return _utc(a.end_at) > datetime.now(UTC)


def _snapshot(a: Appointment) -> dict[str, Any]:
    """Ce qu'il faut garder avant écriture."""
    start, end = _utc(a.start_at), _utc(a.end_at)
    return {
        "business_id": a.business_id,
        "start_at": start,
        "end_at": end,
        "minutes": max(5, int((end - start).total_seconds() // 60)),
        "staff_id": a.staff_id,
        # créneau bloqué : sans prestation
        "service": None if a.status == "blocked" else a.title,
    }


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    db: DbSession,
    principal: CurrentUser,
    start: datetime | None = None,
    end: datetime | None = None,
    staff_id: UUID | None = None,
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
    if staff_id is not None:
        filters.append(Appointment.staff_id == staff_id)
    rows = (
        await db.execute(
            select(Appointment, Customer.full_name, Staff.display_name, Staff.color)
            .outerjoin(Customer, Appointment.customer_id == Customer.id)
            .outerjoin(Staff, Appointment.staff_id == Staff.id)
            .where(*filters)
            .order_by(Appointment.start_at.asc())
            .limit(limit)
        )
    ).all()
    items = [_to_item(a, name, sname, scolor) for a, name, sname, scolor in rows]
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
    staff_id: UUID | None = None
    # premier coiffeur libre si pas de choix
    auto_assign_staff: bool = False
    # compétences en mode auto
    prestation_id: UUID | None = None


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
    await _check_staff(db, bid, body.staff_id)
    # client d'un autre salon : refusé
    if body.customer_id is not None:
        owner = await db.scalar(select(Customer.business_id).where(Customer.id == body.customer_id))
        if owner != bid:
            raise HTTPException(400, "Client inconnu pour ce salon")
    # compétences : mode auto seulement
    auto = body.auto_assign_staff and body.staff_id is None
    skills = await _prestations_for(db, bid, body.prestation_id, body.title if auto else "")
    # jamais de surréservation silencieuse
    staff_id = await _ensure_room(
        db,
        bid,
        body.start_at,
        body.end_at,
        staff_id=body.staff_id,
        auto=body.auto_assign_staff,
        prestation_ids=skills,
    )
    appt = Appointment(
        business_id=bid,
        staff_id=staff_id,
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
    try:
        # course : la base tranche au flush
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
    except Exception as exc:  # créneau déjà occupé
        if not is_slot_taken(exc):
            raise
        await db.rollback()
        raise HTTPException(409, _OVERLAP) from exc
    await db.refresh(appt)
    logger.info("appointment.created", business_id=str(bid), appt_id=str(appt.id))
    return await _item(db, appt)


class AppointmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    status: Literal["scheduled", "confirmed", "cancelled", "completed", "no_show"] | None = None
    staff_notes: str | None = Field(default=None, max_length=5000)
    # null = plus de coiffeur
    staff_id: UUID | None = None


@router.patch("/{appointment_id}", response_model=AppointmentItem)
async def update_appointment(
    appointment_id: UUID, body: AppointmentUpdate, db: DbSession, principal: CurrentUser
) -> AppointmentItem:
    """Met à jour un rendez-vous (horaires, statut, détails)."""
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.business_id != principal.business_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    data = body.model_dump(exclude_unset=True)
    # valeurs cibles, avant toute écriture
    new_start = _utc(data.get("start_at") or appt.start_at)
    new_end = _utc(data.get("end_at") or appt.end_at)
    new_status = data.get("status") or appt.status
    new_staff = data.get("staff_id", appt.staff_id)
    if new_end < new_start:
        raise HTTPException(400, "La fin doit être postérieure au début")
    if "staff_id" in data:
        await _check_staff(db, appt.business_id, new_staff)
    moved = (
        data.get("start_at") is not None
        or data.get("end_at") is not None
        or "staff_id" in data
        or appt.status == "cancelled"
    )
    if moved and new_status != "cancelled":
        await _ensure_room(
            db, appt.business_id, new_start, new_end, staff_id=new_staff, exclude_id=appt.id
        )
    # annulé ou déplacé : place libre
    away = new_end <= _utc(appt.start_at) or new_start >= _utc(appt.end_at)
    frees = new_status == "cancelled" or (away and new_status not in ("completed", "no_show"))
    freed = _snapshot(appt) if frees and _frees_slot(appt) else None
    for f in ("title", "description", "location", "status", "start_at", "end_at", "staff_notes"):
        if f in data and data[f] is not None:
            setattr(appt, f, data[f])
    if "staff_id" in data:
        appt.staff_id = new_staff
    record_audit(
        db,
        business_id=appt.business_id,
        actor=principal.email or "Agent",
        action="appointment.updated",
        entity_type="appointment",
        entity_id=appt.id,
        summary=f"RDV « {appt.title} » mis à jour ({appt.status})",
    )
    try:
        await db.commit()
    except Exception as exc:  # créneau déjà occupé
        if not is_slot_taken(exc):
            raise
        await db.rollback()
        raise HTTPException(409, _OVERLAP) from exc
    if freed is not None:
        await _after_free(db, freed)
    await db.refresh(appt)
    return await _item(db, appt)


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
    logger.info("appointment.deposit_paid", business_id=str(appt.business_id), appt_id=str(appt.id))
    return await _item(db, appt)


@router.delete("/{appointment_id}")
async def delete_appointment(
    appointment_id: UUID, db: DbSession, principal: CurrentUser
) -> dict:
    """Supprime un rendez-vous."""
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.business_id != principal.business_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    title = appt.title
    freed = _snapshot(appt) if _frees_slot(appt) else None
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
    if freed is not None:
        await _after_free(db, freed)
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
    rows: list[Any] = []
    if bid is not None:
        rows = list(
            (
                await db.execute(
                    select(Appointment, Staff.display_name)
                    .outerjoin(Staff, Appointment.staff_id == Staff.id)
                    .where(Appointment.business_id == bid)
                    .order_by(Appointment.start_at.asc())
                    .limit(2000)
                )
            ).all()
        )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jenny//Agenda//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Jenny — Rendez-vous",
    ]
    for a, staff_name in rows:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{a.id}@jenny.ai",
            f"DTSTAMP:{_ics_dt(a.created_at)}",
            f"DTSTART:{_ics_dt(a.start_at)}",
            f"DTEND:{_ics_dt(a.end_at)}",
            f"SUMMARY:{_ics_escape(a.title)}",
            f"STATUS:{_ICS_STATUS.get(a.status, 'TENTATIVE')}",
        ]
        parts = [f"Coiffeur : {staff_name}"] if staff_name else []
        if a.description:
            parts.append(a.description)
        if parts:
            lines.append(f"DESCRIPTION:{_ics_escape(chr(10).join(parts))}")
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
