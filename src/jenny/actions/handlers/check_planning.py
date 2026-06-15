"""Action : Consultation du planning via Google Calendar.

Vérifie les disponibilités et créneaux en temps réel
via l'intégration Google Calendar, ou en mode simulé.
"""

from __future__ import annotations

from typing import ClassVar

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.logging import get_logger
from jenny.integrations.google_calendar import GoogleCalendarService

logger = get_logger(__name__)


class CheckPlanningAction(BaseAction):
    """Consulte le planning et les disponibilités.

    Utilise Google Calendar en production,
    données simulées en dev/test.
    """

    name = "check_planning"
    description = "Vérifie les créneaux disponibles dans le planning"
    required_params: ClassVar[tuple[str, ...]] = ()

    def __init__(self, calendar_service: GoogleCalendarService | None = None) -> None:
        self.calendar = calendar_service or GoogleCalendarService()

    async def execute(self, params: dict) -> dict:
        """Consulte les disponibilités.

        Args:
            params: {"date": "2026-03-16"} — optionnel

        Returns:
            Créneaux disponibles.
        """
        requested_date = params.get("date")

        logger.info(
            "action.check_planning",
            requested_date=requested_date,
            calendar_connected=self.calendar.is_configured,
        )

        # Récupérer les créneaux via Google Calendar
        slots = await self.calendar.get_available_slots(days=7)
        total_slots = len(slots)

        # Regrouper par jour
        days_slots: dict[str, list[str]] = {}
        for slot in slots[:30]:
            key = f"{slot.day_name} {slot.date}"
            if key not in days_slots:
                days_slots[key] = []
            days_slots[key].append(slot.time)

        if requested_date:
            message = (
                f"Pour le {requested_date}, des créneaux sont disponibles. "
                f"Au total, {total_slots} créneaux ouverts cette semaine."
            )
        else:
            message = (
                f"{total_slots} créneaux disponibles cette semaine. Quel jour vous conviendrait ?"
            )

        return ActionResult(
            success=True,
            message=message,
            data={
                "available_slots": days_slots,
                "total_available": total_slots,
                "requested_date": requested_date,
                "calendar_connected": self.calendar.is_configured,
            },
        ).to_dict()
