"""Routes pour la gestion des messages clients.

Endpoints CRUD et de consultation des messages.
Les endpoints d'ingestion sont dans ingest.py.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from jenny.api.dependencies import DbSession
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.message_repo import MessageRepository
from jenny.domain.schemas.message import MessageResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/messages")


class MessageListResponse(BaseModel):
    """Liste paginée de messages."""

    messages: list[MessageResponse]
    next_cursor: str | None = None


def _enforce_tenant(request: Request, business_id: UUID) -> None:
    """Si auth requise, le business_id de la requête doit correspondre au contexte."""
    settings = get_settings()
    if not settings.require_auth:
        return
    ctx_bid = getattr(request.state, "business_id", None)
    if ctx_bid is not None and ctx_bid != business_id:
        raise HTTPException(status_code=403, detail="Accès refusé pour ce business")


@router.get("/", response_model=MessageListResponse)
async def list_messages(
    request: Request,
    db: DbSession,
    business_id: UUID,
    channel: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    cursor: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> MessageListResponse:
    """Liste les messages avec filtres et pagination par curseur."""
    _enforce_tenant(request, business_id)
    repo = MessageRepository(db)
    rows, next_c = await repo.list_by_business_cursor(
        business_id,
        limit=limit,
        cursor=cursor,
        channel=channel,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )
    return MessageListResponse(
        messages=[
            MessageResponse(
                id=str(m.id),
                channel=m.channel,  # type: ignore[arg-type]
                direction=m.direction,  # type: ignore[arg-type]
                sender_name=m.sender_name,
                content=m.content_text,
                status=m.status,
                priority=m.priority,
                category=m.category,
                conversation_id=str(m.conversation_id),
                created_at=m.created_at,
            )
            for m in rows
        ],
        next_cursor=next_c,
    )


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    request: Request,
    db: DbSession,
    message_id: UUID,
    business_id: UUID = Query(  # noqa: B008 — idiome FastAPI (dépendance en valeur par défaut)
        ..., description="ID du business (anti fuite inter-tenant)"
    ),
) -> MessageResponse:
    """Récupère un message par son ID (scopé au business)."""
    _enforce_tenant(request, business_id)
    repo = MessageRepository(db)
    message = await repo.get_by_id_for_business(message_id, business_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message non trouvé")

    return MessageResponse(
        id=str(message.id),
        channel=message.channel,  # type: ignore[arg-type]
        direction=message.direction,  # type: ignore[arg-type]
        sender_name=message.sender_name,
        content=message.content_text,
        status=message.status,
        priority=message.priority,
        category=message.category,
        conversation_id=str(message.conversation_id),
        created_at=message.created_at,
    )
