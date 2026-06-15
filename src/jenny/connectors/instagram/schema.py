"""Schémas pour le connecteur Instagram Messaging API (Meta).

Gère les DMs Instagram reçus via webhook et l'envoi de réponses.
Ref: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Webhook entrant (DM reçu) ──


class IGMessageContent(BaseModel):
    """Contenu d'un message Instagram."""

    mid: str = Field(..., description="Message ID Instagram")
    text: str | None = None


class IGSender(BaseModel):
    """Expéditeur du message."""

    id: str


class IGRecipient(BaseModel):
    """Destinataire du message."""

    id: str


class IGMessaging(BaseModel):
    """Événement de messaging Instagram."""

    sender: IGSender
    recipient: IGRecipient
    timestamp: int
    message: IGMessageContent | None = None


class IGEntry(BaseModel):
    """Entrée du webhook Instagram."""

    id: str
    time: int
    messaging: list[IGMessaging] = Field(default_factory=list)


class IGWebhookPayload(BaseModel):
    """Payload complet du webhook Instagram Messaging.

    Reçu sur POST /webhooks/instagram quand un DM arrive.
    """

    object: str = "instagram"
    entry: list[IGEntry]


# ── Message sortant ──


class IGOutboundMessage(BaseModel):
    """Message sortant vers l'API Instagram Send.

    Ref: https://developers.facebook.com/docs/instagram-platform/
         instagram-api-with-instagram-login/messaging#send-messages
    """

    recipient: dict = Field(..., description='{"id": "USER_ID"}')
    message: dict = Field(..., description='{"text": "Hello"}')
