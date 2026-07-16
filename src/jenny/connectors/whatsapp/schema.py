"""schémas connecteur whatsapp."""

from __future__ import annotations

from pydantic import BaseModel, Field

# webhook entrant


class WhatsAppProfile(BaseModel):
    """profil expéditeur."""

    # nom pas toujours fourni
    name: str | None = None


class WhatsAppContact(BaseModel):
    """contact du webhook."""

    profile: WhatsAppProfile | None = None
    wa_id: str


class WhatsAppText(BaseModel):
    """texte du message."""

    body: str


class WhatsAppMessage(BaseModel):
    """message du webhook."""

    from_: str = Field(..., alias="from")
    id: str
    timestamp: str
    text: WhatsAppText | None = None
    type: str = "text"

    model_config = {"populate_by_name": True}


class WhatsAppMetadata(BaseModel):
    """métadonnées du numéro."""

    display_phone_number: str
    phone_number_id: str


class WhatsAppValue(BaseModel):
    """valeur d'un changement, tout optionnel."""

    messaging_product: str = "whatsapp"
    metadata: WhatsAppMetadata | None = None
    contacts: list[WhatsAppContact] = Field(default_factory=list)
    messages: list[WhatsAppMessage] = Field(default_factory=list)
    # accusés de statut, non traités
    statuses: list[dict] = Field(default_factory=list)


class WhatsAppChange(BaseModel):
    """changement du webhook."""

    value: WhatsAppValue
    field: str = "messages"


class WhatsAppEntry(BaseModel):
    """entrée du webhook."""

    id: str
    changes: list[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    """payload complet du webhook.

    Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
    """

    object: str = "whatsapp_business_account"
    entry: list[WhatsAppEntry]


# message sortant


class WhatsAppOutboundText(BaseModel):
    """texte sortant."""

    preview_url: bool = False
    body: str


class WhatsAppOutboundMessage(BaseModel):
    """message sortant.

    Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
    """

    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: WhatsAppOutboundText
