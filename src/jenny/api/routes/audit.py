"""Journal d'audit : consultation de « qui a fait quoi » (#16).

Lecture seule, scopée au business. Sert à la timeline d'activité de l'équipe et
à la traçabilité. Les écritures se font ailleurs (via ``audit_service``) au fil
des mutations.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.audit_log import AuditLog

logger = get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit"])


class AuditItem(BaseModel):
    id: str
    actor: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    summary: str
    meta: dict | None = None
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditItem]
    total: int


@router.get("", response_model=AuditListResponse)
async def list_audit(
    db: DbSession,
    principal: CurrentUser,
    action: str | None = None,
    actor: str | None = None,
    entity_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditListResponse:
    """Liste l'historique d'audit du business (le plus récent d'abord)."""
    bid = principal.business_id
    if bid is None:
        return AuditListResponse(items=[], total=0)

    filters = [AuditLog.business_id == bid]
    if action:
        filters.append(AuditLog.action == action)
    if actor:
        filters.append(AuditLog.actor == actor)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)

    total = (
        await db.execute(select(func.count(AuditLog.id)).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return AuditListResponse(
        items=[
            AuditItem(
                id=str(a.id),
                actor=a.actor,
                action=a.action,
                entity_type=a.entity_type,
                entity_id=str(a.entity_id) if a.entity_id else None,
                summary=a.summary,
                meta=a.meta,
                created_at=a.created_at,
            )
            for a in rows
        ],
        total=int(total or 0),
    )
