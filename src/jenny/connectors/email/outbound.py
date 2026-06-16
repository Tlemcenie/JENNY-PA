"""Envoi sortant Email (réponse au client par email).

Réutilise ``EmailSender`` (SMTP réel, ou écriture fichier en dev) en lui
injectant les identifiants SMTP DU business (``EmailCreds``) — sinon repli sur
la configuration globale. Renvoie False sans lever si l'envoi échoue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.notifications.email_sender import EmailMessage, EmailSender

if TYPE_CHECKING:
    from jenny.services.channel_credentials_service import EmailCreds

logger = get_logger(__name__)


async def send_email_reply(
    to_email: str | None,
    text: str,
    *,
    creds: EmailCreds | None = None,
    subject: str = "Re: votre message",
    reply_to: str | None = None,
) -> bool:
    """Envoie une réponse par email au client (SMTP business ou repli global)."""
    if not to_email:
        logger.info("email.reply.skipped_no_recipient")
        return False
    sender = EmailSender(creds=creds)
    msg = EmailMessage(to=to_email, subject=subject, body_text=text, reply_to=reply_to)
    try:
        return await sender.send(msg)
    except Exception as e:  # pragma: no cover - dépend du SMTP distant
        logger.error("email.reply.failed", error=str(e), to=to_email)
        return False
