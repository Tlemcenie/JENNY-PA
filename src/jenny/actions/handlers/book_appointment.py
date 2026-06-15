"""Action : Réserver un rendez-vous via Google Calendar.

Gère la prise de rendez-vous en vérifiant la disponibilité
et en créant la réservation dans Google Calendar
(ou en mode simulé si pas de credentials).
"""

from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.logging import get_logger
from jenny.integrations.google_calendar import GoogleCalendarService

logger = get_logger(__name__)


class BookAppointmentAction(BaseAction):
    """Réserve un rendez-vous via Google Calendar."""

    name = "book_appointment"
    description = "Réserve un rendez-vous à la date souhaitée via Google Calendar"
    required_params: ClassVar[tuple[str, ...]] = ("date",)

    def __init__(self, calendar_service: GoogleCalendarService | None = None) -> None:
        self.calendar = calendar_service or GoogleCalendarService()

    async def execute(self, params: dict) -> dict:
        """Réserve un rendez-vous dans Google Calendar.

        Args:
            params: {
                "date": "2026-03-20",
                "time": "14:00",
                "name": "Marie Dupont",
                "email": "marie@example.com",
                "phone": "0612345678",
                "service": "Coupe + Brushing",
            }

        Returns:
            Confirmation de la réservation.
        """
        missing = self.validate_params(params)
        if missing:
            return ActionResult(
                success=False,
                message=f"Paramètres manquants : {missing}",
            ).to_dict()

        date = params["date"]
        time = params.get("time", "10:00")
        customer_name = params.get("name", "Client")
        customer_email = params.get("email", "")
        customer_phone = params.get("phone", "")
        service = params.get("service", "Prestation")
        duration_minutes = int(params.get("duration", 60))

        rdv_id = f"RDV-{uuid4().hex[:8].upper()}"

        logger.info(
            "action.book_appointment",
            rdv_id=rdv_id,
            date=date,
            time=time,
            service=service,
            calendar_connected=self.calendar.is_configured,
        )

        # Construire les datetime ISO
        start_dt = f"{date}T{time}:00"
        # Calculer l'heure de fin
        hour, minute = map(int, time.split(":"))
        total_minutes = hour * 60 + minute + duration_minutes
        end_hour = total_minutes // 60
        end_minute = total_minutes % 60
        end_dt = f"{date}T{end_hour:02d}:{end_minute:02d}:00"

        # Créer l'événement dans Google Calendar
        result = await self.calendar.create_event(
            title=f"{service} — {customer_name}",
            start_datetime=start_dt,
            end_datetime=end_dt,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            service=service,
            description=f"Réf: {rdv_id}\nRéservé via Jenny AI",
        )

        if result.success:
            event_id = result.event.id if result.event else ""
            return ActionResult(
                success=True,
                message=(f"Rendez-vous confirmé pour le {date} à {time}. Référence : {rdv_id}."),
                data={
                    "rdv_id": rdv_id,
                    "calendar_event_id": event_id,
                    "date": date,
                    "time": time,
                    "service": service,
                    "status": "confirmé",
                    "customer_name": customer_name,
                    "calendar_connected": self.calendar.is_configured,
                },
            ).to_dict()
        else:
            return ActionResult(
                success=False,
                message=f"Impossible de réserver le créneau : {result.message}",
                data={"rdv_id": rdv_id, "date": date, "time": time},
            ).to_dict()
