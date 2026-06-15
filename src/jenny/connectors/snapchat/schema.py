"""Schémas pour le connecteur Snapchat for Business.

Gère les messages Snapchat reçus via webhook et l'envoi de réponses.
Ref: https://developers.snap.com/api/marketing-api/Conversions-API
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Webhook entrant ──


class SnapMessage(BaseModel):
    """Message Snapchat individuel."""

    id: str
    sender_id: str
    sender_display_name: str = ""
    text: str
    timestamp: str
    conversation_id: str = ""


class SnapWebhookPayload(BaseModel):
    """Payload du webhook Snapchat.

    Reçu sur POST /webhooks/snapchat quand un message arrive.
    """

    event_type: str = "message"
    messages: list[SnapMessage] = Field(default_factory=list)
    app_id: str = ""


# ── Message sortant ──


class SnapOutboundMessage(BaseModel):
    """Message sortant vers l'API Snapchat."""

    recipient_id: str
    text: str
    conversation_id: str = ""
