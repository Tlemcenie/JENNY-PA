"""Schémas pour le connecteur WhatsApp Business API (Meta Cloud API).

Définit les structures de données pour :
- Les webhooks entrants (messages reçus)
- Les messages sortants (réponses)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Webhook entrant (message reçu) ──


class WhatsAppProfile(BaseModel):
    """Profil de l'expéditeur."""

    # Meta ne fournit pas toujours le nom : on le rend optionnel pour ne pas
    # rejeter un webhook par ailleurs valide.
    name: str | None = None


class WhatsAppContact(BaseModel):
    """Contact dans le webhook."""

    profile: WhatsAppProfile | None = None
    wa_id: str


class WhatsAppText(BaseModel):
    """Contenu texte d'un message."""

    body: str


class WhatsAppMessage(BaseModel):
    """Message individuel dans le webhook."""

    from_: str = Field(..., alias="from")
    id: str
    timestamp: str
    text: WhatsAppText | None = None
    type: str = "text"

    model_config = {"populate_by_name": True}


class WhatsAppMetadata(BaseModel):
    """Métadonnées du numéro de téléphone."""

    display_phone_number: str
    phone_number_id: str


class WhatsAppValue(BaseModel):
    """Valeur d'un changement dans le webhook.

    Une même structure véhicule les messages entrants ET les accusés de statut
    (envoyé/délivré/lu). ``metadata`` et ``contacts`` peuvent être absents selon
    le type d'événement : tout est donc optionnel pour ne jamais rejeter un
    webhook Meta légitime (sinon Meta le renvoie en boucle).
    """

    messaging_product: str = "whatsapp"
    metadata: WhatsAppMetadata | None = None
    contacts: list[WhatsAppContact] = Field(default_factory=list)
    messages: list[WhatsAppMessage] = Field(default_factory=list)
    # Accusés de statut (delivered/read/sent). Non typés finement : on les
    # accepte pour répondre 200, sans les traiter pour l'instant.
    statuses: list[dict] = Field(default_factory=list)


class WhatsAppChange(BaseModel):
    """Changement dans l'entrée du webhook."""

    value: WhatsAppValue
    field: str = "messages"


class WhatsAppEntry(BaseModel):
    """Entrée du webhook WhatsApp."""

    id: str
    changes: list[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    """Payload complet du webhook WhatsApp.

    Reçu sur POST /webhooks/whatsapp quand un message arrive.
    Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
    """

    object: str = "whatsapp_business_account"
    entry: list[WhatsAppEntry]


# ── Message sortant (réponse) ──


class WhatsAppOutboundText(BaseModel):
    """Texte d'un message sortant."""

    preview_url: bool = False
    body: str


class WhatsAppOutboundMessage(BaseModel):
    """Message sortant vers WhatsApp Cloud API.

    Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
    """

    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: WhatsAppOutboundText
