"""Schéma du payload entrant pour les emails.

Définit la structure attendue quand un email est reçu
via un webhook (SendGrid, Mailgun, etc.) ou un polling IMAP.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class EmailAttachment(BaseModel):
    """Pièce jointe d'un email."""

    filename: str
    content_type: str
    size_bytes: int
    url: str | None = None  # URL de stockage (S3, etc.)


class EmailPayload(BaseModel):
    """Payload brut d'un email entrant.

    Ce schéma peut être alimenté par :
    - Un webhook de service email (SendGrid Inbound Parse, Mailgun, etc.)
    - Un polling IMAP
    - Un forwarding automatique
    """

    message_id: str = Field(..., description="Message-ID de l'email (RFC 2822)")
    in_reply_to: str | None = Field(default=None, description="Message-ID du mail auquel on répond")
    thread_id: str | None = Field(default=None, description="ID de thread (Gmail, etc.)")

    from_email: EmailStr
    from_name: str | None = None
    to_email: EmailStr
    reply_to: EmailStr | None = None

    subject: str | None = None
    text_body: str = Field(..., min_length=1)
    html_body: str | None = None

    sent_at: datetime
    received_at: datetime | None = None

    attachments: list[EmailAttachment] = Field(default_factory=list)
    headers: dict = Field(
        default_factory=dict,
        description="Headers email bruts pertinents",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message_id": "<abc123@mail.example.com>",
                    "from_email": "client@example.com",
                    "from_name": "Jean Martin",
                    "to_email": "contact@monbusiness.fr",
                    "subject": "Question sur vos tarifs",
                    "text_body": "Bonjour, pourriez-vous me communiquer vos tarifs ?",
                    "sent_at": "2026-03-10T15:00:00Z",
                }
            ]
        }
    }
