"""Action : le CLIENT gère son propre rendez-vous par chat (annuler/déplacer/confirmer).

Scopée au ``customer_id`` du client : retrouve son prochain rendez-vous et
l'annule, le déplace, ou le confirme. Sans identifiant client (chat anonyme),
Jenny demande au client de s'identifier. Ouvre sa propre session DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_WD = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class ManageAppointmentAction(BaseAction):
    """Annule / déplace / confirme le rendez-vous du client courant."""

    name = "manage_appointment"
    description = "Annule, déplace ou confirme le rendez-vous du client"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        op = params.get("operation") or "cancel"
        bid = params.get("business_id")
        cid = params.get("customer_id")
        if not bid:
            return {"success": False, "message": "Contexte business absent.", "operation": op}
        if not cid:
            # Chat anonyme : on ne peut pas retrouver le RDV sans identifier le client.
            return {"success": False, "needs_identification": True, "operation": op}
        try:
            return await self._manage(UUID(str(bid)), UUID(str(cid)), op, params)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.manage_appt.error", error=str(exc))
            return {"success": False, "operation": op, "message": "Action non aboutie."}

    async def _manage(self, bid: UUID, cid: UUID, op: str, params: dict) -> dict:
        from sqlalchemy import select

        from jenny.db.session import async_session_factory
        from jenny.domain.models.appointment import Appointment
        from jenny.domain.models.business import Business
        from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time
        from jenny.services.availability import business_tz
        from jenny.services.waitlist_service import notify_waitlist_for_freed_slot

        now = datetime.now(UTC)
        async with async_session_factory() as db:
            business = await db.get(Business, bid)
            tz = business_tz(business)
            appt = (
                await db.execute(
                    select(Appointment)
                    .where(
                        Appointment.business_id == bid,
                        Appointment.customer_id == cid,
                        Appointment.status.notin_(["cancelled", "blocked"]),
                        Appointment.start_at >= now,
                    )
                    .order_by(Appointment.start_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if appt is None:
                return {"success": False, "no_appointment": True, "operation": op}

            cur = appt.start_at.astimezone(tz)
            when = f"{_WD[cur.weekday()]} {cur.day:02d}/{cur.month:02d} à {cur.strftime('%Hh%M')}"

            if op == "cancel":
                appt.status = "cancelled"
                # Créneau libéré → on prévient le 1er inscrit en liste d'attente.
                await notify_waitlist_for_freed_slot(
                    db, business_id=bid, service=appt.title, when_label=when
                )
                await db.commit()
                return {"success": True, "operation": "cancel", "when": when, "service": appt.title}

            if op == "confirm":
                appt.status = "confirmed"
                await db.commit()
                return {"success": True, "operation": "confirm", "when": when, "service": appt.title}

            # reschedule : nouvelle date/heure issues des slots du message.
            new_date = parse_fr_date(params.get("date") or "", today=now.astimezone(tz).date())
            new_time = parse_fr_time(params.get("time") or "")
            if new_date is None and new_time is None:
                return {"success": False, "operation": "reschedule", "need_when": True, "when": when}
            duration = appt.end_at - appt.start_at
            day = new_date or cur.date()
            hh = new_time.hour if new_time else cur.hour
            mm = new_time.minute if new_time else cur.minute
            new_local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            appt.start_at = new_local.astimezone(UTC)
            appt.end_at = appt.start_at + duration
            # L'ancien créneau se libère → on prévient la liste d'attente.
            await notify_waitlist_for_freed_slot(
                db, business_id=bid, service=appt.title, when_label=when
            )
            await db.commit()
            new_when = (
                f"{_WD[new_local.weekday()]} {new_local.day:02d}/{new_local.month:02d} "
                f"à {new_local.strftime('%Hh%M')}"
            )
            return {
                "success": True,
                "operation": "reschedule",
                "when": new_when,
                "service": appt.title,
            }
