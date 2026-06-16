"""Service d'envoi d'emails SMTP.

Envoie des emails transactionnels :
- Confirmation de rendez-vous
- Modification de rendez-vous
- Annulation de rendez-vous
- Confirmation de devis
- Confirmation de commande
- Réponse aux réclamations

Configuration requise (variables d'env) :
    JENNY_SMTP_HOST
    JENNY_SMTP_PORT
    JENNY_SMTP_USERNAME
    JENNY_SMTP_PASSWORD
    JENNY_SMTP_FROM_EMAIL
    JENNY_SMTP_FROM_NAME
"""

from __future__ import annotations

import asyncio
import html as html_lib
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EmailMessage:
    """Email à envoyer."""

    to: str
    subject: str
    body_text: str
    body_html: str | None = None
    reply_to: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)


EmailType = Literal[
    "appointment_confirmation",
    "appointment_modification",
    "appointment_cancellation",
    "appointment_reminder",
    "quote_sent",
    "order_confirmation",
    "complaint_acknowledgment",
    "welcome",
]


# ── Templates d'emails ──

TEMPLATES: dict[EmailType, dict[str, str]] = {
    "appointment_confirmation": {
        "subject": "✅ Confirmation de votre rendez-vous — {business_name}",
        "body": """Bonjour {customer_name},

Votre rendez-vous est confirmé !

📅 Date : {date}
🕐 Heure : {time}
📍 Lieu : {location}
💇 Prestation : {service}
💰 Prix estimé : {price}

Référence : {reference}

Pour modifier ou annuler, répondez à cet email ou contactez-nous.

À bientôt !
{business_name}""",
    },
    "appointment_modification": {
        "subject": "📝 Modification de votre rendez-vous — {business_name}",
        "body": """Bonjour {customer_name},

Votre rendez-vous a été modifié.

📅 Nouvelle date : {date}
🕐 Nouvelle heure : {time}
📍 Lieu : {location}
💇 Prestation : {service}

Référence : {reference}

Si ce changement ne vous convient pas, n'hésitez pas à nous contacter.

À bientôt !
{business_name}""",
    },
    "appointment_cancellation": {
        "subject": "❌ Annulation de votre rendez-vous — {business_name}",
        "body": """Bonjour {customer_name},

Votre rendez-vous du {date} à {time} a été annulé.

Référence : {reference}

Si vous souhaitez reprendre rendez-vous, n'hésitez pas à nous contacter.

À bientôt !
{business_name}""",
    },
    "appointment_reminder": {
        "subject": "⏰ Rappel : votre rendez-vous demain — {business_name}",
        "body": """Bonjour {customer_name},

Petit rappel : vous avez un rendez-vous demain !

📅 Date : {date}
🕐 Heure : {time}
📍 Lieu : {location}
💇 Prestation : {service}

Si vous ne pouvez pas venir, merci de nous prévenir au plus tôt.

À demain !
{business_name}""",
    },
    "quote_sent": {
        "subject": "📋 Votre devis — {business_name}",
        "body": """Bonjour {customer_name},

Voici votre devis pour la prestation demandée :

💇 Prestation : {service}
💰 Montant : {price}
📅 Validité : {validity}

Référence : {reference}

Pour accepter ce devis, répondez à cet email ou contactez-nous.

Cordialement,
{business_name}""",
    },
    "order_confirmation": {
        "subject": "📦 Confirmation de commande — {business_name}",
        "body": """Bonjour {customer_name},

Votre commande est confirmée !

🛒 Commande : {reference}
📦 Articles : {items}
💰 Total : {price}

Vous recevrez un email dès l'expédition.

Merci pour votre achat !
{business_name}""",
    },
    "complaint_acknowledgment": {
        "subject": "📩 Votre réclamation a bien été reçue — {business_name}",
        "body": """Bonjour {customer_name},

Nous avons bien reçu votre réclamation et nous en sommes désolés.

Référence : {reference}

Notre équipe examine votre demande et reviendra vers vous
dans les plus brefs délais.

Cordialement,
{business_name}""",
    },
    "welcome": {
        "subject": "👋 Bienvenue chez {business_name} !",
        "body": """Bonjour {customer_name},

Bienvenue chez {business_name} !

Nous sommes ravis de vous compter parmi nos clients.

N'hésitez pas à nous contacter pour toute question.

À très bientôt !
{business_name}""",
    },
}


# Eyebrow + titre serif (heading + accent corail) par type d'email transactionnel.
_HTML_META: dict[str, tuple[str, str, str]] = {
    "appointment_confirmation": ("rendez-vous", "Votre rendez-vous est", "confirmé."),
    "appointment_modification": ("rendez-vous", "Votre rendez-vous a été", "modifié."),
    "appointment_cancellation": ("rendez-vous", "Votre rendez-vous a été", "annulé."),
    "appointment_reminder": ("rappel", "Petit rappel pour votre", "rendez-vous."),
    "quote_sent": ("devis", "Voici votre", "devis."),
    "order_confirmation": ("commande", "Votre commande est", "confirmée."),
    "complaint_acknowledgment": ("support", "Nous avons bien reçu votre", "message."),
    "welcome": ("bienvenue", "Bienvenue chez", "nous."),
}


def _template_html(email_type: str, subject: str, body: str, variables: dict[str, str]) -> str:
    """Habille le corps texte d'un template dans le gabarit premium Jenny."""
    from jenny.notifications.email_layout import MUTED, SANS, render_email

    eyebrow, heading, accent = _HTML_META.get(email_type, ("information", "Information", ""))
    safe = html_lib.escape(body).replace("\n", "<br>")
    block = (
        f'<div style="font-family:{SANS};font-size:15px;line-height:1.7;color:{MUTED};">{safe}</div>'
    )
    return render_email(
        preheader=subject,
        eyebrow=eyebrow,
        heading=heading,
        accent=accent,
        content_html=block,
        app_name="Jenny",
    )


class EmailSender:
    """Service d'envoi d'emails transactionnels via SMTP.

    Supporte Gmail, SendGrid, Mailgun, ou tout serveur SMTP.
    """

    def __init__(self, creds=None) -> None:
        self.settings = get_settings()
        # Paramètres SMTP effectifs : identifiants DU business (``creds``) s'ils
        # sont fournis, sinon configuration globale d'environnement. ``creds=None``
        # ⇒ comportement strictement identique à avant (emails transactionnels).
        self.smtp_host = (getattr(creds, "smtp_host", "") or self.settings.smtp_host)
        self.smtp_port = (getattr(creds, "smtp_port", 0) or self.settings.smtp_port)
        self.smtp_username = (getattr(creds, "smtp_username", "") or self.settings.smtp_username)
        self.smtp_password = (getattr(creds, "smtp_password", "") or self.settings.smtp_password)
        self.smtp_from_email = (getattr(creds, "smtp_from_email", "") or self.settings.smtp_from_email)
        self.smtp_from_name = (getattr(creds, "smtp_from_name", "") or self.settings.smtp_from_name)
        self.smtp_use_tls = (
            creds.smtp_use_tls if creds is not None and hasattr(creds, "smtp_use_tls")
            else self.settings.smtp_use_tls
        )

    def _build_message(self, email: EmailMessage) -> MIMEMultipart:
        """Construit le message MIME."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.smtp_from_name} <{self.smtp_from_email}>"
        msg["To"] = email.to
        msg["Subject"] = email.subject

        if email.reply_to:
            msg["Reply-To"] = email.reply_to
        if email.cc:
            msg["Cc"] = ", ".join(email.cc)

        # Texte brut
        msg.attach(MIMEText(email.body_text, "plain", "utf-8"))

        # HTML (optionnel)
        if email.body_html:
            msg.attach(MIMEText(email.body_html, "html", "utf-8"))

        return msg

    def _send_sync(self, email: EmailMessage) -> bool:
        """Envoi synchrone via SMTP."""
        msg = self._build_message(email)

        all_recipients = [email.to, *email.cc, *email.bcc]

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls()
                if self.smtp_username:
                    server.login(self.smtp_username, self.smtp_password)
                server.sendmail(
                    self.smtp_from_email,
                    all_recipients,
                    msg.as_string(),
                )
            logger.info(
                "email.sent",
                to=email.to,
                subject=email.subject[:50],
            )
            return True
        except smtplib.SMTPException as e:
            logger.error("email.send_failed", error=str(e), to=email.to)
            return False

    def _resolve_backend(self) -> str:
        """Détermine le canal d'envoi effectif.

        ``auto`` : SMTP si des identifiants sont présents, sinon console en test
        et écriture fichier (consultable dans un navigateur) en dev.
        """
        backend = getattr(self.settings, "email_backend", "auto")
        if backend != "auto":
            return backend
        if self.smtp_username and self.smtp_password and self.smtp_from_email:
            return "smtp"
        if self.settings.is_test:
            return "console"
        return "file"

    def _write_file(self, email: EmailMessage) -> bool:
        """Écrit l'email rendu sur disque (HTML ouvrable dans un navigateur)."""
        try:
            directory = Path(getattr(self.settings, "email_preview_dir", "var/emails"))
            directory.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            safe_to = email.to.replace("@", "_at_").replace("/", "_")
            path = directory / f"{ts}-{safe_to}.html"
            content = email.body_html or (
                f"<pre>{html_lib.escape(email.body_text)}</pre>"
            )
            # En-tête commenté : métadonnées + version texte (pratique en dev).
            meta = (
                f"<!--\nTo: {email.to}\nSubject: {email.subject}\n\n"
                f"{email.body_text}\n-->\n"
            )
            path.write_text(meta + content, encoding="utf-8")
            logger.info(
                "email.file_written",
                path=str(path),
                to=email.to,
                subject=email.subject[:60],
            )
            return True
        except OSError as e:
            logger.error("email.file_write_failed", error=str(e), to=email.to)
            return False

    def _log_console(self, email: EmailMessage) -> bool:
        """Trace l'email dans les logs (backend de test)."""
        logger.info(
            "email.console",
            to=email.to,
            subject=email.subject,
            body=email.body_text[:500],
        )
        return True

    async def send(self, email: EmailMessage) -> bool:
        """Envoie un email selon le backend configuré.

        - ``smtp`` : envoi réel (exécuté dans un thread pour ne pas bloquer) ;
        - ``file`` : écrit le HTML sur disque (dev, consultable au navigateur) ;
        - ``console`` : trace dans les logs (tests).
        """
        backend = self._resolve_backend()
        if backend == "file":
            return self._write_file(email)
        if backend == "console":
            return self._log_console(email)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_sync, email)

    async def send_template(
        self,
        email_type: EmailType,
        to: str,
        variables: dict[str, str],
    ) -> bool:
        """Envoie un email basé sur un template.

        Args:
            email_type: Type d'email (appointment_confirmation, etc.).
            to: Adresse email du destinataire.
            variables: Variables à injecter dans le template.

        Returns:
            True si l'envoi a réussi.
        """
        template = TEMPLATES.get(email_type)
        if not template:
            logger.error("email.template_not_found", type=email_type)
            return False

        subject = template["subject"].format(**variables)
        body = template["body"].format(**variables)

        email = EmailMessage(
            to=to,
            subject=subject,
            body_text=body,
            body_html=_template_html(email_type, subject, body, variables),
        )

        logger.info(
            "email.template.sending",
            type=email_type,
            to=to,
        )

        return await self.send(email)

    async def send_appointment_confirmation(
        self,
        to: str,
        customer_name: str,
        date: str,
        time: str,
        location: str,
        service: str,
        price: str,
        reference: str,
        business_name: str,
    ) -> bool:
        """Raccourci pour envoyer une confirmation de RDV."""
        return await self.send_template(
            "appointment_confirmation",
            to,
            {
                "customer_name": customer_name,
                "date": date,
                "time": time,
                "location": location,
                "service": service,
                "price": price,
                "reference": reference,
                "business_name": business_name,
            },
        )

    async def send_appointment_reminder(
        self,
        to: str,
        customer_name: str,
        date: str,
        time: str,
        location: str,
        service: str,
        business_name: str,
    ) -> bool:
        """Raccourci pour envoyer un rappel de RDV."""
        return await self.send_template(
            "appointment_reminder",
            to,
            {
                "customer_name": customer_name,
                "date": date,
                "time": time,
                "location": location,
                "service": service,
                "business_name": business_name,
            },
        )
