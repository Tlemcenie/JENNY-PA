"""Action : le CLIENT gère son propre rendez-vous par chat (annuler/déplacer/confirmer).

Scopée au ``customer_id`` du client : retrouve son prochain rendez-vous et
l'annule, le déplace, ou le confirme. Sans identifiant client (chat anonyme),
Jenny demande au client de s'identifier. Ouvre sa propre session DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from jenny.db.conflicts import is_slot_taken
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
        # Chat anonyme : le RDV pris DANS cette conversation reste gérable via son
        # id (posé en slot au moment de la réservation) — pas besoin d'identifier.
        aid = params.get("appointment_id")
        if not bid:
            return {"success": False, "message": "Contexte business absent.", "operation": op}
        if not cid and not aid:
            # Ni client ni RDV de conversation : impossible de retrouver la réservation.
            return {"success": False, "needs_identification": True, "operation": op}
        try:
            return await self._manage(
                UUID(str(bid)),
                UUID(str(cid)) if cid else None,
                op,
                params,
                appointment_id=UUID(str(aid)) if aid else None,
            )
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.manage_appt.error", error=str(exc))
            return {"success": False, "operation": op, "message": "Action non aboutie."}

    async def _manage(
        self,
        bid: UUID,
        cid: UUID | None,
        op: str,
        params: dict,
        *,
        appointment_id: UUID | None = None,
    ) -> dict:
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
            appt = None
            if cid is not None:
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
            if appt is None and appointment_id is not None:
                # Repli conversation : le RDV pris dans CE fil de discussion.
                cand = await db.get(Appointment, appointment_id)
                if (
                    cand is not None
                    and cand.business_id == bid
                    and cand.status not in ("cancelled", "blocked")
                ):
                    appt = cand
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
            new_start = new_local.astimezone(UTC)

            # Mêmes garde-fous qu'à la réservation : jamais dans le passé, jamais un
            # jour de fermeture, jamais sur un créneau déjà pris. Sinon Jenny
            # « accepterait » verbalement un déplacement impossible.
            from jenny.services.availability import (
                format_slots_fr,
                is_day_closed,
                next_free_slots,
            )

            dur_minutes = max(int(duration.total_seconds() // 60), 15)
            if new_start <= now:
                alts = await next_free_slots(
                    db, bid, dur_minutes, from_day=now.astimezone(tz).date()
                )
                return {
                    "success": False,
                    "operation": "reschedule",
                    "past": True,
                    "when": when,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                }
            if await is_day_closed(db, bid, day):
                alts = await next_free_slots(db, bid, dur_minutes, from_day=day)
                return {
                    "success": False,
                    "operation": "reschedule",
                    "closed": True,
                    "when": when,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                }
            new_end = new_start + duration
            clash = (
                await db.execute(
                    select(Appointment.id).where(
                        Appointment.business_id == bid,
                        Appointment.id != appt.id,
                        Appointment.status.notin_(["cancelled"]),
                        Appointment.start_at < new_end,
                        Appointment.end_at > new_start,
                    )
                )
            ).first()
            if clash is not None:
                alts = await next_free_slots(db, bid, dur_minutes, from_day=day)
                return {
                    "success": False,
                    "operation": "reschedule",
                    "conflict": True,
                    "when": when,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                }

            appt.start_at = new_start
            appt.end_at = appt.start_at + duration
            # L'ancien créneau se libère → on prévient la liste d'attente.
            await notify_waitlist_for_freed_slot(
                db, business_id=bid, service=appt.title, when_label=when
            )
            try:
                await db.commit()
            except Exception as exc:  # créneau pris entre-temps (course)
                if not is_slot_taken(exc):
                    raise
                await db.rollback()
                return {
                    "success": False,
                    "operation": "reschedule",
                    "conflict": True,
                    "message": "Ce créneau vient d'être pris, proposez-en un autre.",
                }
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
