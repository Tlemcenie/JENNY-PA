"""Envoi d'une réponse *humaine* vers le bon connecteur de canal.

Utilisé par la reprise en main depuis le dashboard : un agent répond à un
client et le message part sur le canal d'origine (WhatsApp, Instagram,
Twitter, Snapchat). Le destinataire est encodé dans l'``external_conversation_id``
de la conversation (ex. ``wa:33612345678``, ``ig:17841...``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.connectors.instagram.service import InstagramConnector
from jenny.connectors.snapchat.service import SnapchatConnector
from jenny.connectors.twitter.service import TwitterConnector
from jenny.connectors.whatsapp.service import WhatsAppConnector
from jenny.core.logging import get_logger
from jenny.services import channel_credentials_service as creds_svc

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Connecteurs disposant d'un envoi sortant. Les canaux sans connecteur
# (api, email, form) ne peuvent pas être adressés ici : la réponse est alors
# seulement persistée côté dashboard.
_CONNECTORS = {
    "whatsapp": WhatsAppConnector(),
    "instagram": InstagramConnector(),
    "twitter": TwitterConnector(),
    "snapchat": SnapchatConnector(),
}
# Connecteurs prenant des identifiants PAR BUSINESS (priment sur l'env global).
_PER_BUSINESS = {"whatsapp", "instagram"}


async def send_channel_reply(
    channel: str,
    external_conversation_id: str | None,
    text: str,
    *,
    session: AsyncSession | None = None,
    business_id: UUID | None = None,
) -> bool:
    """Envoie une réponse humaine au client via le connecteur du canal.

    Si ``session`` + ``business_id`` sont fournis, on résout les identifiants DU
    business (base chiffrée, sinon env global) et on les passe au connecteur —
    sinon le connecteur retombe sur l'env. Renvoie ``True`` si l'envoi a réussi ;
    ``False`` (sans lever) si pas de connecteur sortant, destinataire introuvable
    ou échec API — l'appelant persiste alors la réponse avec un statut d'échec.
    """
    if not external_conversation_id or ":" not in external_conversation_id:
        return False
    _, recipient = external_conversation_id.split(":", 1)
    conn = _CONNECTORS.get(channel)
    if conn is None or not recipient:
        return False
    creds = None
    if session is not None and business_id is not None and channel in _PER_BUSINESS:
        try:
            creds = await creds_svc.resolve(session, business_id, channel)
        except Exception as e:  # pragma: no cover - résolution best-effort
            logger.warning("reply_dispatch.creds_resolve_failed", channel=channel, error=str(e))
    try:
        if channel in _PER_BUSINESS:
            return await conn.send_reply(recipient, text, creds=creds)  # type: ignore[call-arg]
        return await conn.send_reply(recipient, text)
    except Exception as e:  # pragma: no cover - dépend d'une API externe
        logger.error("reply_dispatch.send_failed", channel=channel, error=str(e))
        return False
