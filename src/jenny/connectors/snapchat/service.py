"""Connecteur Snapchat for Business.

Gère :
- La réception des messages via webhook
- L'envoi de réponses via l'API Snapchat

Configuration requise (variables d'env) :
    JENNY_SNAPCHAT_CLIENT_ID
    JENNY_SNAPCHAT_CLIENT_SECRET
    JENNY_SNAPCHAT_ACCESS_TOKEN
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from jenny.connectors.base import BaseConnector, RawMessage
from jenny.core.config import get_settings
from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.connectors.snapchat.schema import SnapWebhookPayload

logger = get_logger(__name__)

SNAP_API_BASE = "https://adsapi.snapchat.com/v1"


class SnapchatConnector(BaseConnector):
    """Connecteur Snapchat for Business.

    Flux :
    1. Snapchat envoie un POST sur /webhooks/snapchat
    2. Jenny parse le payload
    3. Le message passe dans le pipeline Jenny
    4. Jenny répond via l'API Snapchat
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pending_messages: list[RawMessage] = []

    @property
    def channel_name(self) -> str:
        return "snapchat"

    def parse_webhook(self, payload: SnapWebhookPayload) -> list[RawMessage]:
        """Parse un webhook Snapchat et extrait les messages.

        Args:
            payload: Payload validé du webhook Snapchat.

        Returns:
            Liste de messages bruts normalisés.
        """
        messages: list[RawMessage] = []

        for msg in payload.messages:
            raw = RawMessage(
                external_id=msg.id,
                channel="snapchat",
                sender=msg.sender_display_name or msg.sender_id,
                content=msg.text,
                raw_payload=payload.model_dump(),
                timestamp=msg.timestamp,
            )
            messages.append(raw)

        logger.info("snapchat.webhook.parsed", count=len(messages))
        self._pending_messages.extend(messages)
        return messages

    async def fetch_messages(self) -> list[RawMessage]:
        """Retourne les messages en attente."""
        messages = list(self._pending_messages)
        self._pending_messages.clear()
        return messages

    async def send_reply(self, recipient_id: str, content: str) -> bool:
        """Envoie un message via l'API Snapchat.

        Args:
            recipient_id: ID Snapchat du destinataire.
            content: Texte de la réponse.

        Returns:
            True si l'envoi a réussi.
        """
        url = f"{SNAP_API_BASE}/conversations/messages"

        headers = {
            "Authorization": f"Bearer {self.settings.snapchat_access_token}",
            "Content-Type": "application/json",
        }

        body = {
            "recipient_id": recipient_id,
            "message": {"text": content},
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=body, headers=headers, timeout=10.0)
                response.raise_for_status()
                logger.info(
                    "snapchat.message.sent",
                    to=recipient_id[:8] + "...",
                    status=response.status_code,
                )
                return True
        except httpx.HTTPError as e:
            logger.error("snapchat.message.failed", error=str(e))
            return False

    async def health_check(self) -> bool:
        """Vérifie la connectivité avec l'API Snapchat."""
        if not self.settings.snapchat_access_token:
            return False
        try:
            url = f"{SNAP_API_BASE}/me"
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.snapchat_access_token}"},
                    timeout=5.0,
                )
                return r.status_code == 200
        except httpx.HTTPError:
            return False
