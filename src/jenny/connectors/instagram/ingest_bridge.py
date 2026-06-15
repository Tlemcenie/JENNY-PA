"""Pont Instagram webhook → MessageIn pour ingestion.

Symétrique de ``connectors/whatsapp/ingest_bridge.py`` : transforme un
événement de messaging Instagram en ``MessageIn`` canonique pour que les DMs
soient persistés (conversation + message) comme tous les autres canaux.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jenny.domain.schemas.message import MessageIn

if TYPE_CHECKING:
    from uuid import UUID

    from jenny.connectors.instagram.schema import IGMessaging, IGWebhookPayload


def payload_recipient_id(payload: IGWebhookPayload) -> str | None:
    """ID du compte Instagram qui REÇOIT le DM (= identifiant du business)."""
    for entry in payload.entry:
        for messaging in entry.messaging:
            rid = messaging.recipient.id
            if rid:
                return rid
    return None


def _ig_timestamp(ts: int) -> datetime:
    """Convertit un timestamp Instagram (millisecondes) en datetime UTC."""
    try:
        secs = ts / 1000 if ts > 1_000_000_000_000 else ts
        return datetime.fromtimestamp(secs, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return datetime.now(UTC)


def ig_messaging_to_message_in(messaging: IGMessaging, business_id: UUID) -> MessageIn:
    """Construit un MessageIn depuis un événement de messaging Instagram."""
    now = datetime.now(UTC)
    sender = messaging.sender.id
    mid = messaging.message.mid if messaging.message else ""
    text = messaging.message.text if messaging.message and messaging.message.text else ""
    body = text.strip() or " "
    return MessageIn(
        external_message_id=mid,
        external_conversation_id=f"ig:{sender}",
        channel="instagram",
        direction="inbound",
        business_id=business_id,
        sender_handle=sender,
        content_text=body,
        source_created_at=_ig_timestamp(messaging.timestamp),
        received_at=now,
        metadata={"instagram": True},
    )
