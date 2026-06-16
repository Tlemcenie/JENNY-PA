"""Connecteur Instagram Messaging API (Meta).

Gère :
- La réception des DMs via webhook
- L'envoi de réponses via l'API Instagram Graph
- La vérification du webhook

Configuration requise (variables d'env) :
    JENNY_INSTAGRAM_PAGE_ID
    JENNY_INSTAGRAM_ACCESS_TOKEN
    JENNY_INSTAGRAM_VERIFY_TOKEN
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from jenny.connectors.base import BaseConnector, RawMessage
from jenny.core.config import get_settings
from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.connectors.instagram.schema import IGWebhookPayload
    from jenny.services.channel_credentials_service import InstagramCreds

logger = get_logger(__name__)

META_GRAPH_API = "https://graph.facebook.com/v21.0"


class InstagramConnector(BaseConnector):
    """Connecteur Instagram Messaging via Meta Graph API.

    Flux :
    1. Meta envoie un POST sur /webhooks/instagram (webhook)
    2. Jenny parse le payload, extrait le DM
    3. Le DM passe dans le pipeline Jenny
    4. Jenny répond via POST sur l'API Instagram Send
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pending_messages: list[RawMessage] = []

    @property
    def channel_name(self) -> str:
        return "instagram"

    def verify_webhook(
        self, mode: str, token: str, challenge: str, creds: InstagramCreds | None = None
    ) -> str | None:
        """Vérifie le webhook Meta (identifiants business prioritaires sur l'env)."""
        expected = creds.verify_token if creds else self.settings.instagram_verify_token
        if mode == "subscribe" and token == expected:
            logger.info("instagram.webhook.verified")
            return challenge
        logger.warning("instagram.webhook.verification_failed")
        return None

    def parse_webhook(self, payload: IGWebhookPayload) -> list[RawMessage]:
        """Parse un webhook Instagram et extrait les DMs.

        Args:
            payload: Payload validé du webhook Instagram.

        Returns:
            Liste de messages bruts normalisés.
        """
        messages: list[RawMessage] = []

        for entry in payload.entry:
            for messaging in entry.messaging:
                if messaging.message is None or messaging.message.text is None:
                    continue

                raw = RawMessage(
                    external_id=messaging.message.mid,
                    channel="instagram",
                    sender=messaging.sender.id,
                    content=messaging.message.text,
                    raw_payload=payload.model_dump(),
                    timestamp=str(messaging.timestamp),
                )
                messages.append(raw)

        logger.info("instagram.webhook.parsed", count=len(messages))
        self._pending_messages.extend(messages)
        return messages

    async def fetch_messages(self) -> list[RawMessage]:
        """Retourne les DMs en attente (reçus via webhook)."""
        messages = list(self._pending_messages)
        self._pending_messages.clear()
        return messages

    async def send_reply(
        self, recipient_id: str, content: str, creds: InstagramCreds | None = None
    ) -> bool:
        """Envoie un DM via l'API Instagram.

        Args:
            recipient_id: ID Instagram du destinataire (IGSID).
            content: Texte de la réponse.
            creds: Identifiants par business (priment sur l'env). Absents → envoi
                désactivé : renvoie False sans lever (état « non connecté »).

        Returns:
            True si l'envoi a réussi.
        """
        access_token = creds.access_token if creds else self.settings.instagram_access_token
        page_id = creds.page_id if creds else self.settings.instagram_page_id
        if not access_token or not page_id:
            logger.info("instagram.send.skipped_not_connected")
            return False

        url = f"{META_GRAPH_API}/{page_id}/messages"

        body = {
            "recipient": {"id": recipient_id},
            "message": {"text": content},
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=body, headers=headers, timeout=10.0)
                response.raise_for_status()
                logger.info(
                    "instagram.message.sent",
                    to=recipient_id[:8] + "...",
                    status=response.status_code,
                )
                return True
        except httpx.HTTPError as e:
            logger.error("instagram.message.failed", error=str(e))
            return False

    async def health_check(self, creds: InstagramCreds | None = None) -> bool:
        """Vérifie la connectivité avec l'API Instagram (identifiants business ou env)."""
        access_token = creds.access_token if creds else self.settings.instagram_access_token
        page_id = creds.page_id if creds else self.settings.instagram_page_id
        if not access_token or not page_id:
            return False
        try:
            url = f"{META_GRAPH_API}/{page_id}"
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5.0,
                )
                return r.status_code == 200
        except httpx.HTTPError:
            return False
