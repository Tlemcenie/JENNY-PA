"""Équipe du salon : coiffeurs et prestations qu'ils font."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.dependencies import CurrentPrincipal, CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff, StaffSkill
from jenny.services.audit_service import record_audit
from jenny.services.availability import (
    _DAY_KEYS,
    _aware,
    _parse_hhmm,
    _staff_bounds,
    business_tz,
    is_day_closed,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/staff", tags=["Staff"])

# couleurs par défaut, une par coiffeur
_PALETTE = ["#E8735A", "#5B8DEF", "#43A882", "#B07CE8", "#E8B04A", "#3FB5C6", "#E86A9A", "#7C8796"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_hours(value: dict | None) -> dict | None:
    """Valide mon..sun -> [début, fin] ou null."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("horaires invalides")
    out: dict[str, list[str] | None] = {}
    for key, win in value.items():
        if key not in _DAY_KEYS:
            raise ValueError(f"jour inconnu : {key}")
        if win is None:
            out[key] = None
            continue
        if not isinstance(win, list | tuple) or len(win) != 2:
            raise ValueError(f"{key} : attendu [début, fin]")
        a, b = _parse_hhmm(str(win[0])), _parse_hhmm(str(win[1]))
        if a is None or b is None or a >= b:
            raise ValueError(f"{key} : heures invalides")
        out[key] = [f"{a[0]:02d}:{a[1]:02d}", f"{b[0]:02d}:{b[1]:02d}"]
    return out


def _clean_color(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _HEX.match(value):
        raise ValueError("couleur attendue au format #rrggbb")
    return value.lower()


class StaffOut(BaseModel):
    id: str
    display_name: str
    color: str | None = None
    is_active: bool
    working_hours: dict | None = None
    # false = seulement prestation_ids
    all_services: bool = True
    prestation_ids: list[str] = []
    upcoming_count: int = 0


class StaffListResponse(BaseModel):
    staff: list[StaffOut]
    total: int


class StaffCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=20)
    is_active: bool = True
    working_hours: dict | None = None
    prestation_ids: list[UUID] = []
    # absent = déduit des prestations
    all_services: bool | None = None

    @field_validator("working_hours")
    @classmethod
    def check_hours(cls, v: dict | None) -> dict | None:
        return _clean_hours(v)

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str | None) -> str | None:
        return _clean_color(v)


class StaffUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    working_hours: dict | None = None
    prestation_ids: list[UUID] | None = None
    all_services: bool | None = None

    @field_validator("working_hours")
    @classmethod
    def check_hours(cls, v: dict | None) -> dict | None:
        return _clean_hours(v)

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str | None) -> str | None:
        return _clean_color(v)


class SkillsPayload(BaseModel):
    prestation_ids: list[UUID] = []
    all_services: bool | None = None


def _require_bid(principal: CurrentPrincipal) -> UUID:
    if principal.business_id is None:
        raise HTTPException(400, "Aucun business associé")
    return principal.business_id


async def _owned(db: AsyncSession, principal: CurrentPrincipal, staff_id: UUID) -> Staff:
    """Coiffeur du salon courant, sinon 404."""
    member = await db.get(Staff, staff_id)
    if member is None or member.business_id != principal.business_id:
        raise HTTPException(404, "Coiffeur introuvable")
    return member


async def _skills_of(db: AsyncSession, ids: list[UUID]) -> dict[UUID, list[str]]:
    out: dict[UUID, list[str]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(StaffSkill.staff_id, StaffSkill.prestation_id).where(
                StaffSkill.staff_id.in_(ids)
            )
        )
    ).all()
    for sid, pid in rows:
        out.setdefault(sid, []).append(str(pid))
    return out


async def _upcoming_of(db: AsyncSession, bid: UUID, ids: list[UUID]) -> dict[UUID, int]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Appointment.staff_id, func.count(Appointment.id))
            .where(
                Appointment.business_id == bid,
                Appointment.staff_id.in_(ids),
                Appointment.status.notin_(["cancelled", "blocked"]),
                Appointment.start_at >= datetime.now(UTC),
            )
            .group_by(Appointment.staff_id)
        )
    ).all()
    return {sid: int(n) for sid, n in rows}


async def _to_out(db: AsyncSession, member: Staff) -> StaffOut:
    skills = await _skills_of(db, [member.id])
    upcoming = await _upcoming_of(db, member.business_id, [member.id])
    return StaffOut(
        id=str(member.id),
        display_name=member.display_name,
        color=member.color,
        is_active=member.is_active,
        working_hours=member.working_hours,
        all_services=member.all_services,
        prestation_ids=skills.get(member.id, []),
        upcoming_count=upcoming.get(member.id, 0),
    )


_NEED_ONE = "Cochez au moins une prestation, ou « Toutes les prestations »"


async def _apply_skills(
    db: AsyncSession,
    bid: UUID,
    member: Staff,
    prestation_ids: list[UUID] | None,
    all_services: bool | None,
) -> None:
    """Pose compétences + drapeau, toujours cohérents."""
    if all_services is True:
        # sait tout faire : liste vidée
        await _set_skills(db, bid, member, [])
        member.all_services = True
        return
    if all_services is None:
        if prestation_ids is None:
            return
        # ancien contrat : vide = tout
        await _set_skills(db, bid, member, prestation_ids)
        member.all_services = not prestation_ids
        return
    if prestation_ids is not None:
        if not prestation_ids:
            raise HTTPException(400, _NEED_ONE)
        await _set_skills(db, bid, member, prestation_ids)
    else:
        count = await db.scalar(
            select(func.count()).select_from(StaffSkill).where(StaffSkill.staff_id == member.id)
        )
        if not count:
            raise HTTPException(400, _NEED_ONE)
    member.all_services = False


async def _set_skills(
    db: AsyncSession, bid: UUID, member: Staff, prestation_ids: list[UUID]
) -> None:
    """Remplace les compétences (prestations du salon)."""
    wanted = list(dict.fromkeys(prestation_ids))
    if wanted:
        found = set(
            (
                await db.execute(
                    select(Prestation.id).where(
                        Prestation.business_id == bid, Prestation.id.in_(wanted)
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(found) != len(wanted):
            raise HTTPException(400, "Prestation inconnue pour ce salon")
    await db.execute(delete(StaffSkill).where(StaffSkill.staff_id == member.id))
    for pid in wanted:
        db.add(StaffSkill(staff_id=member.id, prestation_id=pid))


@router.get("", response_model=StaffListResponse)
async def list_staff(db: DbSession, principal: CurrentUser) -> StaffListResponse:
    """Liste les coiffeurs du salon (actifs d'abord)."""
    bid = principal.business_id
    if bid is None:
        return StaffListResponse(staff=[], total=0)
    rows = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.business_id == bid)
                .order_by(Staff.is_active.desc(), Staff.created_at.asc(), Staff.display_name.asc())
            )
        )
        .scalars()
        .all()
    )
    ids = [m.id for m in rows]
    skills = await _skills_of(db, ids)
    upcoming = await _upcoming_of(db, bid, ids)
    items = [
        StaffOut(
            id=str(m.id),
            display_name=m.display_name,
            color=m.color,
            is_active=m.is_active,
            working_hours=m.working_hours,
            all_services=m.all_services,
            prestation_ids=skills.get(m.id, []),
            upcoming_count=upcoming.get(m.id, 0),
        )
        for m in rows
    ]
    return StaffListResponse(staff=items, total=len(items))


@router.post("", response_model=StaffOut, status_code=201)
async def create_staff(body: StaffCreate, db: DbSession, principal: CurrentUser) -> StaffOut:
    """Ajoute un coiffeur au salon."""
    bid = _require_bid(principal)
    count = await db.scalar(select(func.count(Staff.id)).where(Staff.business_id == bid)) or 0
    member = Staff(
        business_id=bid,
        display_name=body.display_name.strip(),
        color=body.color or _PALETTE[int(count) % len(_PALETTE)],
        is_active=body.is_active,
        working_hours=body.working_hours,
    )
    db.add(member)
    await db.flush()
    await _apply_skills(db, bid, member, body.prestation_ids, body.all_services)
    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "équipe",
        action="staff.created",
        entity_type="staff",
        entity_id=member.id,
        summary=f"Coiffeur « {member.display_name} » ajouté",
    )
    await db.commit()
    await db.refresh(member)
    logger.info("staff.created", business_id=str(bid), staff_id=str(member.id))
    return await _to_out(db, member)


# ── Remplissage ──────────────────────────────────────────────────────────────


class StaffLoad(BaseModel):
    staff_id: str
    display_name: str
    color: str | None = None
    booked_minutes: int
    available_minutes: int
    fill_rate: float  # 0..1


class StaffLoadResponse(BaseModel):
    days: int
    staff: list[StaffLoad]


@router.get("/occupancy", response_model=StaffLoadResponse)
async def staff_occupancy(
    db: DbSession,
    principal: CurrentUser,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
) -> StaffLoadResponse:
    """Taux de remplissage de chaque coiffeur sur N jours."""
    bid = principal.business_id
    if bid is None:
        return StaffLoadResponse(days=days, staff=[])
    business = await db.get(Business, bid)
    tz = business_tz(business)
    members = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.business_id == bid, Staff.is_active.is_(True))
                .order_by(Staff.created_at.asc(), Staff.display_name.asc())
            )
        )
        .scalars()
        .all()
    )
    if not members:
        return StaffLoadResponse(days=days, staff=[])
    today = datetime.now(tz).date()
    win_start = datetime(today.year, today.month, today.day, tzinfo=tz).astimezone(UTC)
    win_end = win_start + timedelta(days=days + 1)
    rows = (
        await db.execute(
            select(
                Appointment.start_at, Appointment.end_at, Appointment.staff_id, Appointment.status
            ).where(
                Appointment.business_id == bid,
                Appointment.status != "cancelled",
                Appointment.start_at < win_end,
                Appointment.end_at > win_start,
            )
        )
    ).all()
    booked = {m.id: 0.0 for m in members}
    avail = {m.id: 0.0 for m in members}
    for i in range(days):
        day = today + timedelta(days=i)
        if await is_day_closed(db, bid, day, business=business):
            continue
        for m in members:
            bounds = _staff_bounds(business, m, day)
            if bounds is None:
                continue
            lo, hi = bounds
            free_min = (hi - lo).total_seconds() / 60
            for bs, be, sid, status in rows:
                if sid != m.id and not (sid is None and status == "blocked"):
                    continue
                a, b = max(_aware(bs), lo), min(_aware(be), hi)
                if b <= a:
                    continue
                minutes = (b - a).total_seconds() / 60
                if status == "blocked":
                    free_min -= minutes  # pas dispo
                else:
                    booked[m.id] += minutes
            avail[m.id] += max(free_min, 0)
    out = [
        StaffLoad(
            staff_id=str(m.id),
            display_name=m.display_name,
            color=m.color,
            booked_minutes=int(booked[m.id]),
            available_minutes=int(avail[m.id]),
            fill_rate=round(min(booked[m.id] / avail[m.id], 1.0), 3) if avail[m.id] else 0.0,
        )
        for m in members
    ]
    return StaffLoadResponse(days=days, staff=out)


@router.get("/{staff_id}", response_model=StaffOut)
async def get_staff(staff_id: UUID, db: DbSession, principal: CurrentUser) -> StaffOut:
    """Détail d'un coiffeur."""
    return await _to_out(db, await _owned(db, principal, staff_id))


@router.patch("/{staff_id}", response_model=StaffOut)
async def update_staff(
    staff_id: UUID, body: StaffUpdate, db: DbSession, principal: CurrentUser
) -> StaffOut:
    """Modifie un coiffeur (nom, couleur, horaires, actif)."""
    member = await _owned(db, principal, staff_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("display_name"):
        member.display_name = data["display_name"].strip()
    if data.get("is_active") is not None:
        member.is_active = data["is_active"]
    # null = repasse aux horaires du salon
    if "working_hours" in data:
        member.working_hours = data["working_hours"]
    if "color" in data:
        member.color = data["color"]
    if data.get("prestation_ids") is not None or data.get("all_services") is not None:
        await _apply_skills(
            db, member.business_id, member, data.get("prestation_ids"), data.get("all_services")
        )
    record_audit(
        db,
        business_id=member.business_id,
        actor=principal.email or "équipe",
        action="staff.updated",
        entity_type="staff",
        entity_id=member.id,
        summary=f"Coiffeur « {member.display_name} » mis à jour",
    )
    await db.commit()
    await db.refresh(member)
    return await _to_out(db, member)


@router.put("/{staff_id}/skills", response_model=StaffOut)
async def set_staff_skills(
    staff_id: UUID, body: SkillsPayload, db: DbSession, principal: CurrentUser
) -> StaffOut:
    """Remplace les prestations du coiffeur (vide = sait tout faire)."""
    member = await _owned(db, principal, staff_id)
    await _apply_skills(db, member.business_id, member, body.prestation_ids, body.all_services)
    await db.commit()
    await db.refresh(member)
    return await _to_out(db, member)


@router.delete("/{staff_id}")
async def delete_staff(staff_id: UUID, db: DbSession, principal: CurrentUser) -> dict:
    """Supprime un coiffeur, ou le désactive s'il a des RDV."""
    member = await _owned(db, principal, staff_id)
    name = member.display_name
    has_rdv = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.staff_id == member.id, Appointment.status != "cancelled"
        )
    )
    # historique gardé : on désactive
    if has_rdv:
        member.is_active = False
        status = "deactivated"
    else:
        await db.execute(delete(StaffSkill).where(StaffSkill.staff_id == member.id))
        await db.delete(member)
        status = "deleted"
    record_audit(
        db,
        business_id=principal.business_id,
        actor=principal.email or "équipe",
        action=f"staff.{status}",
        entity_type="staff",
        entity_id=staff_id,
        summary=f"Coiffeur « {name} » {'désactivé' if has_rdv else 'supprimé'}",
    )
    await db.commit()
    return {"status": status, "id": str(staff_id)}
