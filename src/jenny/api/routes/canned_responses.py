"""Réponses enregistrées : CRUD des modèles de réponse réutilisables.

Permet à un business de gérer une bibliothèque de réponses pré-rédigées que les
agents insèrent dans le composer de l'inbox. Tout est scopé au business du JWT.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.canned_response import CannedResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/canned-responses", tags=["CannedResponses"])


class CannedResponseItem(BaseModel):
    id: str
    shortcut: str | None = None
    title: str
    content: str
    created_at: datetime


class CannedResponseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)
    shortcut: str | None = Field(default=None, max_length=60)


class CannedResponseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=5000)
    shortcut: str | None = Field(default=None, max_length=60)


def _to_item(c: CannedResponse) -> CannedResponseItem:
    return CannedResponseItem(
        id=str(c.id),
        shortcut=c.shortcut,
        title=c.title,
        content=c.content,
        created_at=c.created_at,
    )


@router.get("", response_model=list[CannedResponseItem])
async def list_canned_responses(
    db: DbSession,
    principal: CurrentUser,
) -> list[CannedResponseItem]:
    """Liste les réponses enregistrées du business (par titre)."""
    bid = principal.business_id
    if bid is None:
        return []
    rows = (
        await db.execute(
            select(CannedResponse)
            .where(CannedResponse.business_id == bid)
            .order_by(CannedResponse.title.asc())
        )
    ).scalars().all()
    return [_to_item(c) for c in rows]


@router.post("", response_model=CannedResponseItem, status_code=201)
async def create_canned_response(
    body: CannedResponseCreate,
    db: DbSession,
    principal: CurrentUser,
) -> CannedResponseItem:
    """Crée une réponse enregistrée."""
    if principal.business_id is None:
        raise HTTPException(400, "Aucun business associé")
    canned = CannedResponse(
        business_id=principal.business_id,
        title=body.title,
        content=body.content,
        shortcut=(body.shortcut or None),
    )
    db.add(canned)
    await db.commit()
    await db.refresh(canned)
    logger.info("canned_response.created", canned_id=str(canned.id))
    return _to_item(canned)


async def _load(db: DbSession, canned_id: UUID, business_id: UUID | None) -> CannedResponse:
    canned = await db.get(CannedResponse, canned_id)
    if canned is None or canned.business_id != business_id:
        raise HTTPException(404, "Réponse enregistrée introuvable")
    return canned


@router.patch("/{canned_id}", response_model=CannedResponseItem)
async def update_canned_response(
    canned_id: UUID,
    body: CannedResponseUpdate,
    db: DbSession,
    principal: CurrentUser,
) -> CannedResponseItem:
    """Met à jour une réponse enregistrée (champs fournis uniquement)."""
    canned = await _load(db, canned_id, principal.business_id)
    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(canned, key, value)
    await db.commit()
    await db.refresh(canned)
    return _to_item(canned)


@router.delete("/{canned_id}", status_code=204)
async def delete_canned_response(
    canned_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> None:
    """Supprime une réponse enregistrée."""
    canned = await _load(db, canned_id, principal.business_id)
    await db.delete(canned)
    await db.commit()
    logger.info("canned_response.deleted", canned_id=str(canned_id))
