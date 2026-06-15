"""Mapper email → MessageIn canonique.

Transforme un EmailPayload en MessageIn,
le format unique que le service d'ingestion accepte.
"""

from datetime import UTC, datetime
from uuid import UUID

from jenny.connectors.email.schema import EmailPayload
from jenny.domain.schemas.message import MessageIn


def map_email_to_message_in(
    payload: EmailPayload,
    business_id: UUID,
) -> MessageIn:
    """Transforme un email entrant en MessageIn canonique.

    Args:
        payload: Payload brut de l'email.
        business_id: ID du business destinataire.

    Returns:
        MessageIn prêt pour le service d'ingestion.
    """
    # Résolution du thread pour la conversation
    external_conversation_id = payload.thread_id or payload.in_reply_to or payload.message_id

    # Attachments normalisés
    attachments = [
        {
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes,
            "url": att.url,
        }
        for att in payload.attachments
    ]

    return MessageIn(
        external_message_id=payload.message_id,
        external_conversation_id=external_conversation_id,
        channel="email",
        direction="inbound",
        business_id=business_id,
        sender_name=payload.from_name,
        sender_email=payload.from_email,
        subject=payload.subject,
        content_text=payload.text_body,
        content_html=payload.html_body,
        source_created_at=payload.sent_at,
        received_at=payload.received_at or datetime.now(UTC),
        attachments=attachments,
        metadata={
            "reply_to": payload.reply_to,
            "in_reply_to": payload.in_reply_to,
            "headers": payload.headers,
        },
    )
