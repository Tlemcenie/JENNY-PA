"""Schémas pour le connecteur Twitter/X DM API.

Gère les DMs Twitter reçus via Account Activity API (webhook)
et l'envoi de réponses via l'API v2.
Ref: https://developer.x.com/en/docs/twitter-api/direct-messages
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Webhook entrant (DM reçu via Account Activity API) ──


class TwitterDMMessageData(BaseModel):
    """Données du message DM."""

    id: str
    text: str
    sender_id: str


class TwitterDMMessageCreate(BaseModel):
    """Événement de création de DM."""

    message_data: TwitterDMMessageData
    created_timestamp: str


class TwitterDMEvent(BaseModel):
    """Événement DM dans le webhook."""

    type: str = "message_create"
    id: str
    created_timestamp: str
    message_create: TwitterDMMessageCreate


class TwitterUser(BaseModel):
    """Utilisateur Twitter."""

    id: str
    name: str
    screen_name: str


class TwitterWebhookPayload(BaseModel):
    """Payload du webhook Account Activity API pour les DMs.

    Reçu sur POST /webhooks/twitter quand un DM arrive.
    """

    for_user_id: str = ""
    direct_message_events: list[TwitterDMEvent] = Field(default_factory=list)
    users: dict[str, TwitterUser] = Field(default_factory=dict)


# ── Message sortant ──


class TwitterOutboundDM(BaseModel):
    """Message DM sortant vers l'API Twitter v2."""

    text: str
    participant_id: str = Field(..., description="ID de l'utilisateur destinataire")
