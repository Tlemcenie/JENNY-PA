"""réserve un vrai rdv."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class BookAppointmentDBAction(BaseAction):
    """réserve un rdv en base."""

    name = "book_appointment"
    description = "Réserve un rendez-vous réel (catalogue + agenda du business)"
    required_params: ClassVar[tuple[str, ...]] = ("service", "date")

    async def execute(self, params: dict) -> dict:
        missing = [p for p in self.required_params if not params.get(p)]
        business_id = params.get("business_id")
        if not business_id:
            # pas de contexte business
            return {"success": False, "message": "Contexte business absent.", "missing": list(missing)}
        if missing:
            return {
                "success": False,
                "message": f"Informations manquantes pour réserver : {missing}",
                "missing": missing,
            }

        try:
            return await self._book(UUID(str(business_id)), params)
        except Exception as exc:  # pragma: no cover
            logger.error("action.book_db.error", error=str(exc))
            return {
                "success": False,
                "message": "Réservation non finalisée (à confirmer avec l'équipe).",
            }

    async def _book(self, bid: UUID, params: dict) -> dict:
        from sqlalchemy import and_, func, select

        from jenny.db.session import async_session_factory
        from jenny.domain.models.appointment import Appointment
        from jenny.domain.models.business import Business
        from jenny.domain.models.customer import Customer
        from jenny.engine.datetime_fr import combine_fr, parse_fr_date, parse_fr_time
        from jenny.services.availability import (
            business_tz,
            format_slots_fr,
            free_slots_for_day,
            is_day_closed,
            next_free_slots,
        )
        from jenny.services.prestation_service import (
            _norm,
            load_active_prestations,
            match_prestations,
        )

        async with async_session_factory() as db:
            business = await db.get(Business, bid)
            tz = business_tz(business)

            prestations = await load_active_prestations(db, bid)
            # multi-prestations : cumul durée/prix
            matched = match_prestations(prestations, params["service"])
            if matched:
                service_name = " + ".join(p.name for p in matched)
                duration = sum(p.duration_minutes for p in matched)
                prices = [p.price_eur for p in matched if p.price_cents]
                price_eur = sum(prices) if len(prices) == len(matched) else None
            else:
                duration = int(params.get("duration") or 30)
                service_name = str(params["service"]).strip().capitalize()
                price_eur = None

            day = parse_fr_date(params["date"], today=datetime.now(tz).date())
            if day is None:
                return {"success": False, "message": "Date non comprise.", "missing": ["date"]}

            # fermé → prochain jour ouvert
            if await is_day_closed(db, bid, day, business=business):
                alts = await next_free_slots(db, bid, duration, from_day=day)
                if not alts:
                    # rien à proposer → liste d'attente
                    return {
                        "success": False,
                        "no_slots": True,
                        "service": service_name,
                        "message": "Aucun créneau disponible prochainement.",
                    }
                return {
                    "success": False,
                    "closed": True,
                    "service": service_name,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True),
                    "message": "Le salon est fermé ce jour-là.",
                }

            time_text = params.get("time")
            has_time = bool(time_text) and parse_fr_time(str(time_text)) is not None

            # sans heure : propose des créneaux
            if not has_time:
                slots = await free_slots_for_day(db, bid, day, duration, business=business)
                same_day = bool(slots)
                if not slots:
                    slots = await next_free_slots(db, bid, duration, from_day=day)
                if not slots:
                    return {
                        "success": False,
                        "no_slots": True,
                        "service": service_name,
                        "message": "Aucun créneau disponible prochainement.",
                    }
                return {
                    "success": False,
                    "propose_slots": True,
                    "service": service_name,
                    "slots_text": format_slots_fr(slots[:4], tz, with_day=not same_day),
                }

            # avec heure : vérifie puis réserve
            local_naive = combine_fr(params["date"], str(time_text))
            if local_naive is None:
                return {"success": False, "message": "Heure non comprise.", "missing": ["time"]}
            start = local_naive.replace(tzinfo=tz).astimezone(UTC)
            end = start + timedelta(minutes=duration)

            # jamais réserver dans le passé
            if start <= datetime.now(UTC):
                alts = await next_free_slots(db, bid, duration, from_day=datetime.now(tz).date())
                return {
                    "success": False,
                    "past": True,
                    "service": service_name,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                    "message": "Ce créneau est déjà passé.",
                }

            clash = (
                await db.execute(
                    select(Appointment.id).where(
                        Appointment.business_id == bid,
                        Appointment.status != "cancelled",
                        and_(Appointment.start_at < end, Appointment.end_at > start),
                    )
                )
            ).first()
            if clash is not None:
                alts = await next_free_slots(db, bid, duration, from_day=day)
                return {
                    "success": False,
                    "conflict": True,
                    "service": service_name,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                    "message": "Ce créneau est déjà pris.",
                }

            # client inconnu → pas de rattachement
            raw_customer_id = params.get("customer_id")
            customer_id: UUID | None = None
            if raw_customer_id:
                try:
                    cand = UUID(str(raw_customer_id))
                    if await db.get(Customer, cand) is not None:
                        customer_id = cand
                    else:
                        logger.warning("action.book_db.customer_missing", customer_id=str(cand))
                except (ValueError, TypeError):
                    pass

            # anti double réservation
            also_has = None
            if customer_id and not params.get("allow_double"):
                existing = (
                    await db.execute(
                        select(Appointment)
                        .where(
                            Appointment.business_id == bid,
                            Appointment.customer_id == customer_id,
                            Appointment.status.notin_(["cancelled", "blocked"]),
                            Appointment.start_at >= datetime.now(UTC),
                        )
                        .order_by(Appointment.start_at.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    ex_local = existing.start_at.astimezone(tz)
                    ex_when = (
                        f"{_WEEKDAYS_FR[ex_local.weekday()]} {ex_local.day:02d}/"
                        f"{ex_local.month:02d} à {ex_local.strftime('%Hh%M')}"
                    )
                    same_day = ex_local.date() == start.astimezone(tz).date()
                    same_service = _norm(existing.title or "") == _norm(service_name)
                    if same_day and same_service:
                        # doublon : on demande confirmation
                        return {
                            "success": False,
                            "already_booked": True,
                            "service": service_name,
                            "existing_when": ex_when,
                            "message": "Ce rendez-vous existe déjà.",
                        }
                    also_has = ex_when

            appt = Appointment(
                business_id=bid,
                customer_id=customer_id,
                title=f"{service_name}",
                # formaté depuis le datetime réservé
                description=f"Réservé via Jenny — {start.astimezone(tz).strftime('%d/%m/%Y à %Hh%M')}",
                channel="chat",
                start_at=start,
                end_at=end,
                status="scheduled",
                created_by="Jenny",
            )
            db.add(appt)
            await db.flush()

            local_start = start.astimezone(tz)
            day_label = f"{_WEEKDAYS_FR[local_start.weekday()]} {local_start.day:02d}/{local_start.month:02d}"
            time_label = local_start.strftime("%Hh%M")

            # acompte anti no-show
            from jenny.services.deposit_service import create_deposit_for_appointment

            force_deposit = False
            if customer_id:
                no_shows = (
                    await db.execute(
                        select(func.count(Appointment.id)).where(
                            Appointment.business_id == bid,
                            Appointment.customer_id == customer_id,
                            Appointment.status == "no_show",
                        )
                    )
                ).scalar_one() or 0
                force_deposit = int(no_shows) >= 2

            deposit = await create_deposit_for_appointment(
                db,
                business=business,
                appointment=appt,
                price_eur=price_eur,
                service_name=service_name,
                force=force_deposit,
            )

            # notifie le coiffeur
            from jenny.domain.models.notification import Notification

            notif_body = f"{service_name} — {day_label} à {time_label}."
            if deposit:
                notif_body += f" Acompte {deposit['amount_eur']:.0f}€ en attente."
            db.add(
                Notification(
                    business_id=bid,
                    recipient=None,
                    kind="booking",
                    title="Nouveau rendez-vous pris par Jenny",
                    body=notif_body,
                    meta={"appointment_id": str(appt.id)},
                )
            )
            await db.commit()
            await db.refresh(appt)

            # nom manquant → demandé après
            ask_name = customer_id is None
            if customer_id:
                cust = await db.get(Customer, customer_id)
                if cust is not None and not (cust.full_name or "").strip():
                    ask_name = True

            logger.info("action.book_db.ok", appt_id=str(appt.id), business_id=str(bid))
            return {
                "success": True,
                "message": f"Rendez-vous confirmé : {service_name} le {day_label} à {time_label}.",
                "appointment_id": str(appt.id),
                "service": service_name,
                "day": day_label,
                "time": time_label,
                "duration_minutes": duration,
                "price_eur": price_eur,
                "deposit": deposit,
                "also_has": also_has,
                "ask_name": ask_name,
            }
