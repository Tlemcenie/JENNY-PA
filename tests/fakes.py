"""Faux pour les tests moteur."""

from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

from jenny.actions.base import ActionResult, BaseAction


class BookAppointmentAction(BaseAction):
    """Résa sans base, pour le moteur."""

    name = "book_appointment"
    description = "Réservation simulée (tests)"
    required_params: ClassVar[tuple[str, ...]] = ("date",)

    def __init__(self, calendar_service: object | None = None) -> None:
        self.calendar = calendar_service

    async def execute(self, params: dict) -> dict:
        missing = self.validate_params(params)
        if missing:
            return ActionResult(
                success=False, message=f"Paramètres manquants : {missing}"
            ).to_dict()
        date = params["date"]
        time = params.get("time", "10:00")
        rdv_id = f"RDV-{uuid4().hex[:8].upper()}"
        return ActionResult(
            success=True,
            message=f"Rendez-vous confirmé pour le {date} à {time}. Référence : {rdv_id}.",
            data={
                "rdv_id": rdv_id,
                "date": date,
                "time": time,
                "service": params.get("service", "Prestation"),
                "status": "confirmé",
                "customer_name": params.get("name", "Client"),
            },
        ).to_dict()
