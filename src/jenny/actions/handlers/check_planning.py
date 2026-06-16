"""Action : consultation des disponibilités RÉELLES du salon.

Lit les créneaux libres directement dans l'agenda métier (Postgres) via le
service de disponibilités — les MÊMES données que la réservation, donc cohérent
avec l'anti-double-réservation. Fini les créneaux simulés Google Calendar.

Robuste : sans contexte business, renvoie un résultat non abouti sans planter.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

# Granularité par défaut pour une vue planning (un vrai RDV ajuste sa durée).
_DEFAULT_DURATION_MIN = 30


class CheckPlanningAction(BaseAction):
    """Consulte les créneaux libres réels du salon (agenda DB)."""

    name = "check_planning"
    description = "Vérifie les créneaux disponibles réels dans le planning"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        business_id = params.get("business_id")
        if not business_id:
            return {"success": False, "message": "Contexte business absent."}
        try:
            return await self._check(UUID(str(business_id)), params)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.check_planning.error", error=str(exc))
            return {"success": False, "message": "Planning indisponible pour le moment."}

    async def _check(self, bid: UUID, params: dict) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.domain.models.business import Business
        from jenny.engine.datetime_fr import parse_fr_date
        from jenny.services.availability import (
            business_tz,
            format_slots_fr,
            free_slots_for_day,
            is_day_closed,
            next_free_slots,
        )

        requested = params.get("date")
        async with async_session_factory() as db:
            business = await db.get(Business, bid)
            tz = business_tz(business)
            duration = _DEFAULT_DURATION_MIN

            day = parse_fr_date(str(requested), today=datetime.now(tz).date()) if requested else None

            if day is not None:
                if await is_day_closed(db, bid, day):
                    alts = await next_free_slots(db, bid, duration, from_day=day)
                    return {
                        "success": True,
                        "closed": True,
                        "message": "Le salon est fermé ce jour-là.",
                        "slots_text": format_slots_fr(alts[:6], tz, with_day=True) if alts else "",
                        "requested_date": str(requested),
                    }
                slots = await free_slots_for_day(db, bid, day, duration, business=business)
                same_day = bool(slots)
                if not slots:
                    slots = await next_free_slots(db, bid, duration, from_day=day)
            else:
                slots = await next_free_slots(db, bid, duration)
                same_day = False

            if not slots:
                return {
                    "success": True,
                    "no_slots": True,
                    "message": "Aucun créneau disponible prochainement.",
                    "total_available": 0,
                }

            slots_text = format_slots_fr(slots[:8], tz, with_day=not same_day)
            if requested:
                message = f"Pour cette date, voici des créneaux libres : {slots_text}."
            else:
                message = f"Voici les prochains créneaux disponibles : {slots_text}."

            return {
                "success": True,
                "message": message,
                "slots_text": slots_text,
                "total_available": len(slots),
                "requested_date": str(requested) if requested else None,
            }
