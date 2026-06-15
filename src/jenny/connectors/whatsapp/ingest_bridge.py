"""Pont WhatsApp webhook → MessageIn pour ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jenny.domain.schemas.message import MessageIn

if TYPE_CHECKING:
    from uuid import UUID

    from jenny.connectors.whatsapp.schema import WhatsAppMessage, WhatsAppWebhookPayload


def payload_phone_number_id(payload: WhatsAppWebhookPayload) -> str | None:
    """Extrait le phone_number_id du premier bloc utile."""
    for entry in payload.entry:
        for change in entry.changes:
            meta = change.value.metadata
            if meta and meta.phone_number_id:
                return meta.phone_number_id
    return None


def message_to_message_in(
    msg: WhatsAppMessage,
    business_id: UUID,
    contact_names: dict[str, str],
) -> MessageIn:
    """Construit un MessageIn depuis un message WhatsApp Cloud API."""
    ts = int(msg.timestamp)
    source_at = datetime.fromtimestamp(ts, tz=UTC)
    now = datetime.now(UTC)
    sender = msg.from_
    name = contact_names.get(sender)
    body = (msg.text.body if msg.text else "").strip() or " "
    return MessageIn(
        external_message_id=msg.id,
        external_conversation_id=f"wa:{sender}",
        channel="whatsapp",
        direction="inbound",
        business_id=business_id,
        sender_name=name,
        sender_phone=sender,
        content_text=body,
        source_created_at=source_at,
        received_at=now,
        metadata={"whatsapp": True},
    )
