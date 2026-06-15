"""Connecteur Twitter/X DM API.

Gère :
- La réception des DMs via Account Activity API (webhook)
- L'envoi de DMs via l'API v2
- La vérification CRC du webhook

Configuration requise (variables d'env) :
    JENNY_TWITTER_API_KEY
    JENNY_TWITTER_API_SECRET
    JENNY_TWITTER_ACCESS_TOKEN
    JENNY_TWITTER_ACCESS_TOKEN_SECRET
    JENNY_TWITTER_BEARER_TOKEN
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import TYPE_CHECKING

import httpx

from jenny.connectors.base import BaseConnector, RawMessage
from jenny.core.config import get_settings
from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.connectors.twitter.schema import TwitterWebhookPayload

logger = get_logger(__name__)

TWITTER_API_V2 = "https://api.twitter.com/2"


class TwitterConnector(BaseConnector):
    """Connecteur Twitter/X via Account Activity API + API v2.

    Flux :
    1. Twitter envoie un POST sur /webhooks/twitter (Account Activity)
    2. Jenny parse le payload DM
    3. Le DM passe dans le pipeline Jenny
    4. Jenny répond via POST sur l'API v2 DM
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pending_messages: list[RawMessage] = []

    @property
    def channel_name(self) -> str:
        return "twitter"

    def compute_crc_response(self, crc_token: str) -> str:
        """Calcule la réponse CRC pour la vérification du webhook.

        Twitter envoie un GET avec crc_token, on doit retourner
        un HMAC-SHA256 signé avec notre consumer secret.

        Args:
            crc_token: Token CRC envoyé par Twitter.

        Returns:
            Réponse CRC au format sha256=<base64>.
        """
        sha256_hash = hmac.new(
            self.settings.twitter_api_secret.encode("utf-8"),
            msg=crc_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        response_token = "sha256=" + base64.b64encode(sha256_hash).decode("utf-8")
        logger.info("twitter.crc.computed")
        return response_token

    def parse_webhook(self, payload: TwitterWebhookPayload) -> list[RawMessage]:
        """Parse un webhook Twitter et extrait les DMs.

        Args:
            payload: Payload validé du webhook.

        Returns:
            Liste de messages bruts normalisés.
        """
        messages: list[RawMessage] = []

        for event in payload.direct_message_events:
            if event.type != "message_create":
                continue

            sender_id = event.message_create.message_data.sender_id

            # Ne pas traiter nos propres messages
            if sender_id == payload.for_user_id:
                continue

            # Résoudre le nom d'utilisateur
            user = payload.users.get(sender_id)
            sender_name = f"@{user.screen_name}" if user else sender_id

            raw = RawMessage(
                external_id=event.id,
                channel="twitter",
                sender=sender_name,
                content=event.message_create.message_data.text,
                raw_payload=payload.model_dump(),
                timestamp=event.created_timestamp,
            )
            messages.append(raw)

        logger.info("twitter.webhook.parsed", count=len(messages))
        self._pending_messages.extend(messages)
        return messages

    async def fetch_messages(self) -> list[RawMessage]:
        """Retourne les DMs en attente."""
        messages = list(self._pending_messages)
        self._pending_messages.clear()
        return messages

    async def send_reply(self, recipient_id: str, content: str) -> bool:
        """Envoie un DM via l'API Twitter v2.

        Args:
            recipient_id: ID Twitter du destinataire.
            content: Texte de la réponse.

        Returns:
            True si l'envoi a réussi.
        """
        url = f"{TWITTER_API_V2}/dm_conversations/with/{recipient_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.settings.twitter_bearer_token}",
            "Content-Type": "application/json",
        }

        body = {"text": content}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=body, headers=headers, timeout=10.0)
                response.raise_for_status()
                logger.info(
                    "twitter.dm.sent",
                    to=recipient_id,
                    status=response.status_code,
                )
                return True
        except httpx.HTTPError as e:
            logger.error("twitter.dm.failed", error=str(e))
            return False

    async def health_check(self) -> bool:
        """Vérifie la connectivité avec l'API Twitter."""
        if not self.settings.twitter_bearer_token:
            return False
        try:
            url = f"{TWITTER_API_V2}/users/me"
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.twitter_bearer_token}"},
                    timeout=5.0,
                )
                return r.status_code == 200
        except httpx.HTTPError:
            return False
