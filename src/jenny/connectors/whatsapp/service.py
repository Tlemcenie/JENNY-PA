"""Connecteur WhatsApp Business API (Meta Cloud API).

Gère :
- La réception des messages via webhook
- L'envoi de réponses via l'API Cloud
- La vérification du webhook (challenge)

Configuration requise (variables d'env) :
    JENNY_WHATSAPP_PHONE_NUMBER_ID
    JENNY_WHATSAPP_ACCESS_TOKEN
    JENNY_WHATSAPP_VERIFY_TOKEN
"""

from __future__ import annotations

import httpx

from jenny.connectors.base import BaseConnector, RawMessage
from jenny.connectors.whatsapp.schema import (
    WhatsAppOutboundMessage,
    WhatsAppOutboundText,
    WhatsAppWebhookPayload,
)
from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)

META_API_BASE = "https://graph.facebook.com"


class WhatsAppConnector(BaseConnector):
    """Connecteur WhatsApp via Meta Cloud API.

    Flux :
    1. Meta envoie un POST sur /webhooks/whatsapp (webhook)
    2. Jenny parse le payload, extrait le message
    3. Le message passe dans le pipeline Jenny (intent → agent → réponse)
    4. Jenny envoie la réponse via POST sur l'API Meta
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pending_messages: list[RawMessage] = []

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Vérifie le webhook lors de l'enregistrement Meta.

        Meta envoie un GET avec hub.mode, hub.verify_token, hub.challenge.
        On retourne le challenge si le token correspond.
        """
        if mode == "subscribe" and token == self.settings.whatsapp_verify_token:
            logger.info("whatsapp.webhook.verified")
            return challenge
        logger.warning("whatsapp.webhook.verification_failed")
        return None

    def parse_webhook(self, payload: WhatsAppWebhookPayload) -> list[RawMessage]:
        """Parse un webhook WhatsApp et extrait les messages texte.

        Args:
            payload: Payload validé du webhook.

        Returns:
            Liste de messages bruts normalisés.
        """
        messages: list[RawMessage] = []

        for entry in payload.entry:
            for change in entry.changes:
                value = change.value
                # Construire un mapping wa_id → nom (le nom peut être absent)
                contact_map = {
                    c.wa_id: (c.profile.name if c.profile and c.profile.name else c.wa_id)
                    for c in value.contacts
                }

                for msg in value.messages:
                    if msg.type != "text" or msg.text is None:
                        logger.debug("whatsapp.skipping_non_text", type=msg.type)
                        continue

                    sender_id = msg.from_
                    raw = RawMessage(
                        external_id=msg.id,
                        channel="whatsapp",
                        sender=contact_map.get(sender_id, sender_id),
                        content=msg.text.body,
                        raw_payload=payload.model_dump(),
                        timestamp=msg.timestamp,
                    )
                    messages.append(raw)

        logger.info("whatsapp.webhook.parsed", count=len(messages))
        self._pending_messages.extend(messages)
        return messages

    async def fetch_messages(self) -> list[RawMessage]:
        """Retourne les messages en attente (reçus via webhook)."""
        messages = list(self._pending_messages)
        self._pending_messages.clear()
        return messages

    async def send_reply(self, recipient_phone: str, content: str) -> bool:
        """Envoie un message texte via l'API WhatsApp Cloud.

        Args:
            recipient_phone: Numéro du destinataire (format international).
            content: Texte de la réponse.

        Returns:
            True si l'envoi a réussi.
        """
        url = (
            f"{META_API_BASE}/{self.settings.whatsapp_api_version}"
            f"/{self.settings.whatsapp_phone_number_id}/messages"
        )

        outbound = WhatsAppOutboundMessage(
            to=recipient_phone,
            text=WhatsAppOutboundText(body=content),
        )

        headers = {
            "Authorization": f"Bearer {self.settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=outbound.model_dump(),
                    headers=headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info(
                    "whatsapp.message.sent",
                    to=recipient_phone[:6] + "***",
                    status=response.status_code,
                )
                return True
        except httpx.HTTPError as e:
            logger.error("whatsapp.message.failed", error=str(e))
            return False

    async def health_check(self) -> bool:
        """Vérifie la connectivité avec l'API WhatsApp."""
        if not self.settings.whatsapp_access_token:
            return False
        try:
            url = (
                f"{META_API_BASE}/{self.settings.whatsapp_api_version}"
                f"/{self.settings.whatsapp_phone_number_id}"
            )
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.whatsapp_access_token}"},
                    timeout=5.0,
                )
                return r.status_code == 200
        except httpx.HTTPError:
            return False
