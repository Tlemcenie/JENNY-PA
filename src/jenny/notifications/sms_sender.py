"""Service d'envoi de SMS via Twilio.

Envoie des SMS transactionnels :
- Rappels de rendez-vous
- Confirmation de rendez-vous
- Modification / annulation
- Notifications urgentes

Configuration requise (variables d'env) :
    JENNY_TWILIO_ACCOUNT_SID
    JENNY_TWILIO_AUTH_TOKEN
    JENNY_TWILIO_PHONE_NUMBER
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

SmsType = Literal[
    "appointment_reminder",
    "appointment_confirmation",
    "appointment_modification",
    "appointment_cancellation",
    "custom",
]


# ── Templates SMS ──

SMS_TEMPLATES: dict[SmsType, str] = {
    "appointment_reminder": (
        "⏰ Rappel {business_name} : "
        "RDV demain {date} à {time} pour {service}. "
        "📍 {location}. "
        "Répondez ANNULER pour annuler."
    ),
    "appointment_confirmation": (
        "✅ {business_name} : RDV confirmé le {date} à {time} "
        "pour {service}. Réf: {reference}. "
        "📍 {location}"
    ),
    "appointment_modification": (
        "📝 {business_name} : RDV modifié → {date} à {time}. "
        "Réf: {reference}. Répondez OK pour confirmer."
    ),
    "appointment_cancellation": (
        "❌ {business_name} : Votre RDV du {date} à {time} "
        "est annulé. Réf: {reference}. "
        "Contactez-nous pour reprendre RDV."
    ),
}


@dataclass
class SmsResult:
    """Résultat de l'envoi d'un SMS."""

    success: bool
    message_sid: str | None = None
    error: str | None = None


class SmsSender:
    """Service d'envoi de SMS via Twilio.

    Utilise l'API REST Twilio pour envoyer des SMS.
    Prend en charge les templates prédéfinis et les messages custom.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def _api_url(self) -> str:
        """URL de l'API Twilio pour ce compte."""
        return f"{TWILIO_API_BASE}/Accounts/{self.settings.twilio_account_sid}/Messages.json"

    @property
    def _auth(self) -> tuple[str, str]:
        """Credentials HTTP Basic pour Twilio."""
        return (self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    async def send_sms(self, to: str, body: str) -> SmsResult:
        """Envoie un SMS via Twilio.

        Args:
            to: Numéro du destinataire (format international, ex: +33612345678).
            body: Contenu du SMS (max 1600 caractères).

        Returns:
            SmsResult avec statut et SID du message.
        """
        if not self.settings.twilio_account_sid:
            logger.warning("sms.twilio_not_configured")
            return SmsResult(success=False, error="Twilio non configuré")

        # Twilio limite les SMS à 1600 caractères
        if len(body) > 1600:
            body = body[:1597] + "..."

        data = {
            "To": to,
            "From": self.settings.twilio_phone_number,
            "Body": body,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._api_url,
                    data=data,
                    auth=self._auth,
                    timeout=15.0,
                )

                if response.status_code in (200, 201):
                    result = response.json()
                    logger.info(
                        "sms.sent",
                        to=to[:6] + "***",
                        sid=result.get("sid", ""),
                    )
                    return SmsResult(
                        success=True,
                        message_sid=result.get("sid"),
                    )
                else:
                    error_msg = response.text
                    logger.error(
                        "sms.send_failed",
                        status=response.status_code,
                        error=error_msg[:200],
                    )
                    return SmsResult(success=False, error=error_msg)

        except httpx.HTTPError as e:
            logger.error("sms.http_error", error=str(e))
            return SmsResult(success=False, error=str(e))

    async def send_template(
        self,
        sms_type: SmsType,
        to: str,
        variables: dict[str, str],
    ) -> SmsResult:
        """Envoie un SMS basé sur un template.

        Args:
            sms_type: Type de SMS (appointment_reminder, etc.).
            to: Numéro du destinataire.
            variables: Variables à injecter dans le template.

        Returns:
            SmsResult avec statut.
        """
        template = SMS_TEMPLATES.get(sms_type)
        if not template:
            logger.error("sms.template_not_found", type=sms_type)
            return SmsResult(success=False, error=f"Template '{sms_type}' introuvable")

        body = template.format(**variables)

        logger.info(
            "sms.template.sending",
            type=sms_type,
            to=to[:6] + "***",
        )

        return await self.send_sms(to, body)

    async def send_appointment_reminder(
        self,
        to: str,
        customer_name: str,
        date: str,
        time: str,
        service: str,
        location: str,
        business_name: str,
    ) -> SmsResult:
        """Raccourci pour envoyer un rappel de RDV par SMS.

        Args:
            to: Numéro du client (ex: +33612345678).
            customer_name: Nom du client.
            date: Date du RDV (ex: "Jeudi 20 mars").
            time: Heure du RDV (ex: "14h00").
            service: Prestation (ex: "Coupe + Brushing").
            location: Adresse du salon.
            business_name: Nom du business.

        Returns:
            SmsResult avec statut.
        """
        return await self.send_template(
            "appointment_reminder",
            to,
            {
                "customer_name": customer_name,
                "date": date,
                "time": time,
                "service": service,
                "location": location,
                "business_name": business_name,
            },
        )

    async def send_appointment_confirmation(
        self,
        to: str,
        date: str,
        time: str,
        service: str,
        location: str,
        reference: str,
        business_name: str,
    ) -> SmsResult:
        """Raccourci pour envoyer une confirmation de RDV par SMS."""
        return await self.send_template(
            "appointment_confirmation",
            to,
            {
                "date": date,
                "time": time,
                "service": service,
                "location": location,
                "reference": reference,
                "business_name": business_name,
            },
        )

    async def health_check(self) -> bool:
        """Vérifie la connectivité avec Twilio."""
        if not self.settings.twilio_account_sid:
            return False
        try:
            url = f"{TWILIO_API_BASE}/Accounts/{self.settings.twilio_account_sid}.json"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, auth=self._auth, timeout=5.0)
                return r.status_code == 200
        except httpx.HTTPError:
            return False
