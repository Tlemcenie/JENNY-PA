"""Envoi d'un message AU CLIENT (pas au gérant).

Avant, les rappels, créneaux libérés et confirmations s'arrêtaient sur une
notification interne du tableau de bord : aucun message ne partait jamais.
Ce module choisit le meilleur canal joignable et envoie vraiment.

Ordre : le canal d'origine de la conversation (WhatsApp, Instagram…), sinon
SMS, sinon e-mail. Ne lève jamais : renvoie le canal utilisé, ou None.
Offre ou relance (commercial=True) : plafond anti-spam appliqué ici.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

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


async def _deliver(
    db: AsyncSession,
    business_id: UUID,
    text: str,
    customer_id: UUID | None,
    conversation_id: UUID | None,
    subject: str,
) -> str | None:
    """Essaie les canaux dans l'ordre."""
    from jenny.domain.models.customer import Customer

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


async def _commercial_gate(
    db: AsyncSession,
    business_id: UUID,
    customer_id: UUID | None,
    conversation_id: UUID | None,
    max_per_week: int,
):
    """Plafond : (autorisé, place prise, client)."""
    from jenny.domain.models.conversation import Conversation
    from jenny.domain.models.customer import Customer
    from jenny.services.offer_cap import claim_offer

    cid = customer_id
    if conversation_id is not None:
        conv = await db.get(Conversation, conversation_id)
        if conv is not None and conv.business_id != business_id:
            # fil d'un autre salon
            return False, None, None
        if cid is None and conv is not None:
            cid = conv.customer_id
    if cid is None:
        # pas de fiche client
        return True, None, None
    cust = await db.get(Customer, cid)
    if cust is None or cust.business_id != business_id:
        return False, None, None
    claim = await claim_offer(db, cust, max_per_week=max_per_week)
    return claim is not None, claim, cust


async def notify_customer(
    db: AsyncSession,
    *,
    business_id: UUID,
    text: str,
    customer_id: UUID | None = None,
    conversation_id: UUID | None = None,
    subject: str = "Votre rendez-vous",
    commercial: bool = False,
    max_per_week: int = 1,
) -> str | None:
    """Envoie `text` au client. Renvoie le canal utilisé, ou None.

    commercial=True : offre ou relance, soumise au plafond anti-spam.
    """
    claim = cust = None
    try:
        if commercial:
            ok, claim, cust = await _commercial_gate(
                db, business_id, customer_id, conversation_id, max_per_week
            )
            if not ok:
                logger.info("outbound.capped", business_id=str(business_id))
                return None
        # fiche trouvée via la conv
        target = customer_id or (cust.id if cust is not None else None)
        canal = await _deliver(db, business_id, text, target, conversation_id, subject)
        if canal is None and claim is not None:
            # rien parti : on rend la place
            from jenny.services.offer_cap import release_offer

            await release_offer(db, claim, cust)
        return canal
    except Exception as exc:  # jamais bloquant : un rappel raté ne casse rien
        logger.error("outbound.failed", error=str(exc))
        if claim is not None:
            try:
                from jenny.services.offer_cap import release_offer

                await release_offer(db, claim, cust)
            except Exception:  # session cassée
                pass
        return None
