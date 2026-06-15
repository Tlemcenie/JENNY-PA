"""Service de création des notifications agent (#14/#15).

Crée une ligne ``notifications`` et pousse un événement SSE ``notification.new``
pour que la cloche du dashboard réagisse en temps réel. L'écriture DB rejoint la
transaction du caller ; l'événement SSE doit être publié APRÈS le commit (via
``publish_notification_event``) — voir ``notify_and_publish`` pour le cas simple
où la notification est autonome (sa propre transaction).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from jenny.core.events import publish_notification_event
from jenny.core.logging import get_logger
from jenny.domain.models.notification import Notification

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def build_notification(
    session: AsyncSession,
    *,
    business_id: UUID,
    kind: str,
    title: str,
    recipient: str | None = None,
    body: str | None = None,
    conversation_id: UUID | str | None = None,
    meta: dict | None = None,
) -> Notification:
    """Ajoute une notification à la session (sans commit) et la renvoie.

    Le caller commit puis appelle :func:`publish_notification_event` (ou utilise
    :func:`notify_and_publish` qui gère sa propre transaction).
    """
    cid: UUID | None
    if isinstance(conversation_id, str):
        try:
            cid = UUID(conversation_id)
        except (ValueError, TypeError):
            cid = None
    else:
        cid = conversation_id
    notif = Notification(
        business_id=business_id,
        recipient=recipient,
        kind=kind,
        title=title,
        body=body,
        conversation_id=cid,
        meta=meta,
    )
    session.add(notif)
    return notif


async def notify_and_publish(
    session: AsyncSession,
    *,
    business_id: UUID,
    kind: str,
    title: str,
    recipient: str | None = None,
    body: str | None = None,
    conversation_id: UUID | str | None = None,
    meta: dict | None = None,
) -> Notification:
    """Crée la notification, commit, puis pousse l'événement SSE.

    À utiliser quand la notification est l'opération principale (pas greffée sur
    une autre mutation). Pour greffer sur une transaction existante, préférer
    :func:`build_notification` puis publier l'événement après le commit du caller.
    """
    notif = build_notification(
        session,
        business_id=business_id,
        kind=kind,
        title=title,
        recipient=recipient,
        body=body,
        conversation_id=conversation_id,
        meta=meta,
    )
    await session.commit()
    await session.refresh(notif)
    publish_notification_event(
        business_id,
        recipient=recipient,
        kind=kind,
        title=title,
        conversation_id=notif.conversation_id,
        notification_id=notif.id,
    )
    logger.info("notification.created", kind=kind, recipient=recipient)
    return notif
