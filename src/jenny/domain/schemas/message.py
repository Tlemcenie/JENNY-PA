"""Schémas Pydantic v2 pour les messages.

Définit le format canonique d'entrée (MessageIn), le format
normalisé enrichi (MessageNormalized), et les schémas API.

MessageIn est le contrat unique que TOUS les connecteurs
doivent produire avant toute logique métier.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

ChannelType = Literal[
    "instagram", "whatsapp", "messenger", "twitter", "snapchat", "email", "form"
]
DirectionType = Literal["inbound", "outbound"]


# ── Schéma canonique d'entrée (produit par les connecteurs) ──


class MessageIn(BaseModel):
    """Payload canonique d'un message entrant.

    C'est le format unique que chaque connecteur (form, email,
    WhatsApp, Instagram, Messenger) doit produire. Il ne contient
    aucune intelligence métier — seulement les données brutes normalisées.
    """

    external_message_id: str = Field(..., description="ID unique du message côté canal source")
    external_conversation_id: str | None = Field(
        default=None, description="ID de conversation côté canal (si applicable)"
    )
    channel: ChannelType
    direction: DirectionType = "inbound"

    business_id: UUID
    customer_id: UUID | None = None

    # ── Infos expéditeur ──
    sender_name: str | None = None
    sender_email: EmailStr | None = None
    sender_phone: str | None = None
    sender_handle: str | None = None

    # ── Contenu ──
    subject: str | None = None
    content_text: str = Field(..., min_length=1)
    content_html: str | None = None
    language: str | None = None

    # ── Timestamps ──
    source_created_at: datetime
    received_at: datetime

    # ── Pièces jointes & metadata ──
    attachments: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "external_message_id": "form:contact-123:2026-03-10T14:00:00",
                    "channel": "form",
                    "direction": "inbound",
                    "business_id": "550e8400-e29b-41d4-a716-446655440000",
                    "sender_name": "Marie Dupont",
                    "sender_email": "marie@example.com",
                    "content_text": "Bonjour, je voudrais un devis pour une prestation photo.",
                    "source_created_at": "2026-03-10T14:00:00Z",
                    "received_at": "2026-03-10T14:00:01Z",
                }
            ]
        }
    }


# ── Schéma normalisé / enrichi (post-traitement) ──


class MessageNormalized(BaseModel):
    """Message après normalisation et enrichissement.

    Version prête pour les services, agents et modèles ML.
    Produit par le job ARQ `normalize_message`.
    """

    message_id: UUID
    conversation_id: UUID
    business_id: UUID
    customer_id: UUID | None = None

    channel: ChannelType
    direction: DirectionType

    raw_text: str
    cleaned_text: str
    detected_language: str | None = None

    has_attachments: bool = False
    attachment_count: int = 0

    # ── Signaux ML (remplis progressivement) ──
    intent_label: str | None = None
    priority_score: float | None = None
    sentiment_score: float | None = None
    urgency_flag: bool = False

    normalized_at: datetime


# ── Schémas API (anciens, conservés pour compatibilité) ──


class MessageCreate(BaseModel):
    """Payload simplifié de création (legacy, sera remplacé par MessageIn)."""

    channel: ChannelType
    sender: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)


class MessageResponse(BaseModel):
    """Réponse retournée après création / lecture d'un message.

    `channel` est volontairement un `str` libre : c'est une projection de
    lecture qui doit refléter fidèlement la valeur stockée en base (api,
    twitter, snapchat…), sans re-valider le contrat d'entrée des connecteurs.
    """

    id: str
    channel: str
    direction: DirectionType = "inbound"
    sender_name: str | None = None
    content: str
    status: str = "received"
    priority: int | None = None
    category: str | None = None
    conversation_id: str | None = None
    created_at: datetime | None = None
