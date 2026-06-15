"""Centre de notifications de l'agent (#14/#15).

Liste les notifications destinées à l'agent courant (``recipient == email`` ou
diffusion à toute l'équipe, ``recipient is null``), le compteur non lues, et
permet de les marquer lues. Le push temps réel passe par le bus SSE
(``notification.new``) ; ces endpoints servent le chargement initial et l'état.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.notification import Notification

logger = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationItem(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None = None
    conversation_id: str | None = None
    read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationItem]
    unread: int
    total: int


def _recipient_filter(email: str | None):
    """Notifications visibles par l'agent : les siennes + les diffusions équipe."""
    if email:
        return or_(Notification.recipient == email, Notification.recipient.is_(None))
    return Notification.recipient.is_(None)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    db: DbSession,
    principal: CurrentUser,
    only_unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationListResponse:
    """Liste les notifications récentes de l'agent (les plus récentes d'abord)."""
    bid = principal.business_id
    if bid is None:
        return NotificationListResponse(notifications=[], unread=0, total=0)

    base = [Notification.business_id == bid, _recipient_filter(principal.email)]

    unread = (
        await db.execute(
            select(func.count(Notification.id)).where(
                *base, Notification.read_at.is_(None)
            )
        )
    ).scalar_one()
    total = (
        await db.execute(select(func.count(Notification.id)).where(*base))
    ).scalar_one()

    filters = list(base)
    if only_unread:
        filters.append(Notification.read_at.is_(None))
    rows = (
        await db.execute(
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return NotificationListResponse(
        notifications=[
            NotificationItem(
                id=str(n.id),
                kind=n.kind,
                title=n.title,
                body=n.body,
                conversation_id=str(n.conversation_id) if n.conversation_id else None,
                read=n.read_at is not None,
                created_at=n.created_at,
            )
            for n in rows
        ],
        unread=int(unread or 0),
        total=int(total or 0),
    )


class UnreadCount(BaseModel):
    unread: int


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(db: DbSession, principal: CurrentUser) -> UnreadCount:
    """Compteur léger des notifications non lues (pour le badge de la cloche)."""
    bid = principal.business_id
    if bid is None:
        return UnreadCount(unread=0)
    n = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.business_id == bid,
                _recipient_filter(principal.email),
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    return UnreadCount(unread=int(n or 0))


@router.post("/read-all", response_model=UnreadCount)
async def mark_all_read(db: DbSession, principal: CurrentUser) -> UnreadCount:
    """Marque comme lues toutes les notifications visibles par l'agent."""
    bid = principal.business_id
    if bid is None:
        return UnreadCount(unread=0)
    await db.execute(
        update(Notification)
        .where(
            Notification.business_id == bid,
            _recipient_filter(principal.email),
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return UnreadCount(unread=0)


@router.post("/{notification_id}/read", response_model=UnreadCount)
async def mark_read(
    notification_id: str, db: DbSession, principal: CurrentUser
) -> UnreadCount:
    """Marque une notification comme lue et renvoie le nouveau compteur non lues."""
    bid = principal.business_id
    if bid is not None:
        await db.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.business_id == bid,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        await db.commit()
    return await unread_count(db, principal)
