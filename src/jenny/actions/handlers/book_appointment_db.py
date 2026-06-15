"""Action : réserver un VRAI rendez-vous en base (cas coiffeur).

S'appuie sur le catalogue de prestations (durée + prix réels), comprend les
dates/heures en français (« mardi à 14h »), vérifie qu'il n'y a pas de conflit,
et crée un ``Appointment`` réel rattaché au business. Le résultat alimente la
réponse de Jenny pour une confirmation fondée (jamais inventée).

Robuste par construction : toute incertitude (date incomprise, info manquante)
renvoie un résultat « non abouti » exploité par le slot-filling, sans planter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class BookAppointmentDBAction(BaseAction):
    """Réserve un rendez-vous réel en base à partir du catalogue de prestations."""

    name = "book_appointment"
    description = "Réserve un rendez-vous réel (catalogue + agenda du business)"
    required_params: ClassVar[tuple[str, ...]] = ("service", "date")

    async def execute(self, params: dict) -> dict:
        missing = [p for p in self.required_params if not params.get(p)]
        business_id = params.get("business_id")
        if not business_id:
            # Pas de contexte business : on laisse Jenny gérer en conversation.
            return {"success": False, "message": "Contexte business absent.", "missing": list(missing)}
        if missing:
            return {
                "success": False,
                "message": f"Informations manquantes pour réserver : {missing}",
                "missing": missing,
            }

        try:
            return await self._book(UUID(str(business_id)), params)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
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
            # Multi-prestations : « coupe et couleur » → durée + prix cumulés.
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

            # Fermeture exceptionnelle (congé/férié) → on propose le prochain jour ouvert.
            if await is_day_closed(db, bid, day):
                alts = await next_free_slots(db, bid, duration, from_day=day)
                return {
                    "success": False,
                    "closed": True,
                    "service": service_name,
                    "alternatives_text": format_slots_fr(alts, tz, with_day=True) if alts else "",
                    "message": "Le salon est fermé ce jour-là.",
                }

            time_text = params.get("time")
            has_time = bool(time_text) and parse_fr_time(str(time_text)) is not None

            # ── Sans heure → Jenny PROPOSE des créneaux libres réels ──
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

            # ── Avec heure → on vérifie la dispo puis on réserve ──
            local_naive = combine_fr(params["date"], str(time_text))
            if local_naive is None:
                return {"success": False, "message": "Heure non comprise.", "missing": ["time"]}
            start = local_naive.replace(tzinfo=tz).astimezone(UTC)
            end = start + timedelta(minutes=duration)

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

            # Résolution SÛRE du client : un customer_id qui ne correspond à aucun
            # client réel (id éphémère du chat, etc.) ne doit JAMAIS faire échouer la
            # réservation sur une violation de clé étrangère (Postgres l'applique,
            # SQLite non — d'où le bug invisible en test). Si le client n'existe pas,
            # on réserve sans le rattacher plutôt que de planter.
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

            # ── Anti-double-réservation : le client a-t-il déjà un RDV à venir ? ──
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
                        # Quasi-doublon → on ne crée rien, on demande confirmation.
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
                description=f"Réservé via Jenny ({params['date']} {params.get('time', '')})".strip(),
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

            # ── Acompte anti-no-show (si le salon l'a activé, OU si récidive de lapin) ──
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

            # Notifie le coiffeur de la nouvelle réservation prise par Jenny.
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

            # ── Nom manquant (ex. WhatsApp sans nom de profil) → on le demandera ──
            ask_name = False
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
