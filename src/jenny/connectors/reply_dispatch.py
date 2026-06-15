"""Envoi d'une réponse *humaine* vers le bon connecteur de canal.

Utilisé par la reprise en main depuis le dashboard : un agent répond à un
client et le message part sur le canal d'origine (WhatsApp, Instagram,
Twitter, Snapchat). Le destinataire est encodé dans l'``external_conversation_id``
de la conversation (ex. ``wa:33612345678``, ``ig:17841...``).
"""

from __future__ import annotations

from jenny.connectors.instagram.service import InstagramConnector
from jenny.connectors.snapchat.service import SnapchatConnector
from jenny.connectors.twitter.service import TwitterConnector
from jenny.connectors.whatsapp.service import WhatsAppConnector
from jenny.core.logging import get_logger

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


async def send_channel_reply(
    channel: str,
    external_conversation_id: str | None,
    text: str,
) -> bool:
    """Envoie une réponse humaine au client via le connecteur du canal.

    Renvoie ``True`` si l'envoi a réussi. Renvoie ``False`` (sans lever) si le
    canal n'a pas de connecteur sortant, si le destinataire est introuvable, ou
    si l'API distante échoue — dans tous ces cas l'appelant persiste quand même
    la réponse (avec un statut d'échec de livraison).
    """
    if not external_conversation_id or ":" not in external_conversation_id:
        return False
    _, recipient = external_conversation_id.split(":", 1)
    conn = _CONNECTORS.get(channel)
    if conn is None or not recipient:
        return False
    try:
        return await conn.send_reply(recipient, text)
    except Exception as e:  # pragma: no cover - dépend d'une API externe
        logger.error("reply_dispatch.send_failed", channel=channel, error=str(e))
        return False
