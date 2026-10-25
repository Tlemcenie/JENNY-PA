"""Envoi d'un message AU CLIENT (pas au gérant).

Avant, les rappels, créneaux libérés et confirmations s'arrêtaient sur une
notification interne du tableau de bord : aucun message ne partait jamais.
Ce module choisit le meilleur canal joignable et envoie vraiment.

Ordre : le canal d'origine de la conversation (WhatsApp, Instagram…), sinon
SMS, sinon e-mail. Ne lève jamais : renvoie le canal utilisé, ou None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# canaux avec un vrai connecteur sortant
_CANAUX_DIRECTS = {"whatsapp", "instagram", "twitter", "snapchat"}


async def _via_conversation(
    db: AsyncSession, business_id: UUID, conversation_id: UUID | None, text: str
) -> str | None:
    """Répond sur le canal d'origine du client."""
    if conversation_id is None:
        return None
    from jenny.connectors.reply_dispatch import send_channel_reply
    from jenny.domain.models.conversation import Conversation

    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.channel not in _CANAUX_DIRECTS:
        return None
    if not conv.external_conversation_id:
        return None
    ok = await send_channel_reply(
        conv.channel,
        conv.external_conversation_id,
        text,
        session=db,
        business_id=business_id,
    )
    return conv.channel if ok else None


async def _via_sms(phone: str | None, text: str) -> str | None:
    """Repli SMS (Twilio)."""
    if not phone:
        return None
    from jenny.notifications.sms_sender import SmsSender

    res = await SmsSender().send_sms(phone, text)
    return "sms" if res.success else None


async def _via_email(email: str | None, subject: str, text: str) -> str | None:
    """Dernier repli : e-mail."""
    if not email:
        return None
    from jenny.notifications.email_sender import EmailMessage, EmailSender

    ok = await EmailSender().send(EmailMessage(to=email, subject=subject, body_text=text))
    return "email" if ok else None


async def notify_customer(
    db: AsyncSession,
    *,
    business_id: UUID,
    text: str,
    customer_id: UUID | None = None,
    conversation_id: UUID | None = None,
    subject: str = "Votre rendez-vous",
) -> str | None:
    """Envoie `text` au client. Renvoie le canal utilisé, ou None."""
    from jenny.domain.models.customer import Customer

    try:
        canal = await _via_conversation(db, business_id, conversation_id, text)
        if canal:
            logger.info("outbound.sent", channel=canal, business_id=str(business_id))
            return canal

        cust = await db.get(Customer, customer_id) if customer_id else None
        if cust is None or cust.business_id != business_id:
            logger.info("outbound.no_customer", business_id=str(business_id))
            return None

        canal = await _via_sms(cust.phone, text)
        if canal is None:
            canal = await _via_email(cust.email, subject, text)
        if canal:
            logger.info("outbound.sent", channel=canal, business_id=str(business_id))
        else:
            logger.warning("outbound.unreachable", customer_id=str(cust.id))
        return canal
    except Exception as exc:  # jamais bloquant : un rappel raté ne casse rien
        logger.error("outbound.failed", error=str(exc))
        return None
