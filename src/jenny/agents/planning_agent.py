"""Agent Planning — Consultation et gestion du planning.

Gère les demandes liées au calendrier :
- Consultation des disponibilités (via Google Calendar ou simulé)
- Prochain créneau disponible (urgent)
- Créneaux disponibles pour une date donnée
- Réservation de rendez-vous

Intégration :
    - Google Calendar API (production) → lecture/écriture en temps réel
    - Mode simulé (dev/test) → données fictives
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.integrations.google_calendar import GoogleCalendarService

if TYPE_CHECKING:
    from jenny.actions.registry import ActionRegistry
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)


class PlanningAgent:
    """Agent spécialisé dans la gestion du planning.

    Utilise Google Calendar pour :
    - Voir les disponibilités en temps réel
    - Proposer le prochain créneau libre
    - Réserver/modifier/annuler des RDV
    """

    name: str = "planning"

    def __init__(
        self,
        action_registry: ActionRegistry | None = None,
        calendar_service: GoogleCalendarService | None = None,
    ) -> None:
        self.registry = action_registry
        self.calendar = calendar_service or GoogleCalendarService()

    async def handle(self, state: ConversationState) -> dict:
        """Traite une demande de consultation planning.

        Détecte l'urgence et propose les créneaux adaptés.

        Args:
            state: État de la conversation.

        Returns:
            Créneaux disponibles et/ou confirmation de RDV.
        """
        logger.info("planning_agent.handling", intent=state.current_intent)

        # Chercher une date spécifique dans les slots
        requested_date = None
        is_urgent = False
        for slot_name, slot in state.slots.items():
            if slot.filled and slot_name == "date":
                requested_date = slot.value

        # Détecter l'urgence dans le message
        last_msg = ""
        user_msgs = [m for m in state.message_history if m["role"] == "user"]
        if user_msgs:
            last_msg = user_msgs[-1]["content"].lower()

        urgency_keywords = [
            "urgent",
            "rapidement",
            "vite",
            "asap",
            "le plus tôt",
            "le plus rapide",
            "au plus vite",
            "dès que possible",
            "en urgence",
            "tout de suite",
        ]
        is_urgent = any(kw in last_msg for kw in urgency_keywords)

        # Exécuter via le registre si disponible
        if self.registry is not None:
            action = self.registry.get_action("planning")
            if action is not None:
                try:
                    result = await action.execute({"date": requested_date})
                    return {
                        "response": result.get("message", "Planning consulté."),
                        "documents": [],
                        "action_result": result,
                    }
                except Exception as e:
                    logger.error("planning_agent.action_error", error=str(e))

        # ── Mode urgent : trouver le prochain créneau dispo ──
        if is_urgent:
            next_slot = await self.calendar.get_next_available_slot()
            if next_slot:
                response = (
                    f"🚨 Créneau urgent trouvé !\n\n"
                    f"Le prochain rendez-vous disponible est :\n"
                    f"📅 **{next_slot.day_name} {next_slot.date}** à **{next_slot.time}**\n\n"
                    f"Souhaitez-vous que je réserve ce créneau immédiatement ?"
                )
                return {
                    "response": response,
                    "documents": [],
                    "action_result": {
                        "success": True,
                        "type": "urgent_slot",
                        "slot": {
                            "date": next_slot.date,
                            "time": next_slot.time,
                            "end_time": next_slot.end_time,
                            "day_name": next_slot.day_name,
                        },
                    },
                }
            else:
                return {
                    "response": "Désolé, aucun créneau n'est disponible dans les 7 prochains jours. "
                    "Souhaitez-vous être placé sur liste d'attente ?",
                    "documents": [],
                    "action_result": {"success": False, "type": "no_slots"},
                }

        # ── Créneaux disponibles (normal) ──
        available_slots = await self.calendar.get_available_slots(days=7)

        if not available_slots:
            return {
                "response": "Aucun créneau disponible pour le moment. Essayez une autre semaine.",
                "documents": [],
                "action_result": {"success": False, "type": "no_slots"},
            }

        # Regrouper par jour
        days: dict[str, list] = {}
        for slot in available_slots[:30]:  # Max 30 créneaux affichés
            key = f"{slot.day_name} {slot.date}"
            if key not in days:
                days[key] = []
            days[key].append(slot.time)

        if requested_date:
            response = f"Voici les disponibilités pour le {requested_date} :\n\n"
        else:
            response = "📅 Voici nos disponibilités :\n\n"

        for day, times in days.items():
            times_str = " | ".join(times)
            response += f"  🗓️ {day} : {times_str}\n"

        response += (
            "\n💡 Indiquez le jour et l'heure qui vous conviennent et je réserve immédiatement !"
        )

        if self.calendar.is_configured:
            response += "\n✅ Calendrier synchronisé en temps réel."

        return {
            "response": response,
            "documents": [],
            "action_result": {
                "success": True,
                "type": "planning_info",
                "available_slots_count": len(available_slots),
                "calendar_connected": self.calendar.is_configured,
            },
        }

    async def book_appointment(
        self,
        date: str,
        time: str,
        customer_name: str = "",
        customer_email: str = "",
        customer_phone: str = "",
        service: str = "",
    ) -> dict:
        """Réserve un RDV directement dans Google Calendar.

        Args:
            date: Date (YYYY-MM-DD).
            time: Heure (HH:MM).
            customer_name: Nom du client.
            customer_email: Email.
            customer_phone: Téléphone.
            service: Prestation (ex: "Coupe + Brushing").

        Returns:
            Résultat de la réservation.
        """
        start = f"{date}T{time}:00"
        # Calculer la fin (1h par défaut)
        hour = int(time.split(":")[0])
        end = f"{date}T{hour + 1:02d}:{time.split(':')[1]}:00"

        title = f"{service or 'RDV'} — {customer_name or 'Client'}"

        result = await self.calendar.create_event(
            title=title,
            start_datetime=start,
            end_datetime=end,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            service=service,
        )

        if result.success:
            return {
                "response": (
                    f"✅ Rendez-vous confirmé !\n\n"
                    f"📅 {date} à {time}\n"
                    f"✂️ {service or 'Prestation'}\n"
                    f"👤 {customer_name or 'Client'}\n"
                    f"📧 Confirmation envoyée à {customer_email}\n\n"
                    f"Référence : {result.event.id if result.event else 'N/A'}"
                ),
                "documents": [],
                "action_result": {
                    "success": True,
                    "type": "appointment_booked",
                    "event_id": result.event.id if result.event else None,
                    "date": date,
                    "time": time,
                    "service": service,
                },
            }
        else:
            return {
                "response": f"❌ {result.message}",
                "documents": [],
                "action_result": {"success": False, "error": result.message},
            }
