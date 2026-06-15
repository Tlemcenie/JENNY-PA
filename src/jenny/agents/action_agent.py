"""Agent d'exécution d'actions — Lancement d'actions externes.

Gère les demandes qui nécessitent une action concrète :
- Vérifier le statut d'une commande
- Créer un rendez-vous
- Créer un ticket support
- Déclencher un processus métier

Utilise le registre d'actions pour trouver et exécuter
la bonne action en fonction de l'intention et des entités.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.engine.state_manager import ConversationPhase, ConversationState

if TYPE_CHECKING:
    from jenny.actions.registry import ActionRegistry

logger = get_logger(__name__)


# Slots requis par intention pour exécuter l'action
REQUIRED_SLOTS: dict[str, list[str]] = {
    "order_status": ["order_number"],
    # RDV coiffeur : prestation + jour suffisent pour que l'action s'exécute.
    # Sans l'heure, l'action PROPOSE des créneaux libres ; avec l'heure, elle
    # vérifie la dispo et réserve. Jenny demande la prestation/le jour si besoin.
    "appointment": ["service", "date"],
    # Gestion d'un RDV existant : l'action gère elle-même les infos manquantes.
    "manage_appointment": [],
    # Inscription liste d'attente : aucune info bloquante (on prend ce qu'on a).
    "join_waitlist": [],
    # Enregistrement du nom : le nom est déjà dans le slot.
    "set_customer_name": [],
    "complaint": [],  # Pas de slot requis pour enregistrer
}


class ActionAgent:
    """Agent d'exécution d'actions externes.

    Vérifie que toutes les informations nécessaires sont
    disponibles, puis exécute l'action correspondante.
    """

    name: str = "action"

    def __init__(
        self,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.registry = action_registry

    async def handle(self, state: ConversationState) -> dict:
        """Traite une demande d'action.

        1. Détermine les slots requis pour l'action
        2. Vérifie que tous les slots sont remplis
        3. Exécute l'action via le registre
        4. Retourne le résultat

        Args:
            state: État de la conversation.

        Returns:
            Résultat de l'action avec message et données.
        """
        intent = state.current_intent or "general"

        # ── Vérifier les slots requis ──
        required = REQUIRED_SLOTS.get(intent, [])
        for slot_name in required:
            if slot_name not in state.slots or not state.slots[slot_name].filled:
                # Marquer les slots manquants comme requis
                from jenny.engine.state_manager import ExtractedSlot

                if slot_name not in state.slots:
                    state.slots[slot_name] = ExtractedSlot(name=slot_name, required=True)
                else:
                    state.slots[slot_name].required = True
                state.phase = ConversationPhase.SLOT_FILLING

        # S'il manque des infos, le moteur demandera
        if state.has_missing_required_slots():
            return {
                "response": "J'ai besoin de plus d'informations.",
                "documents": [],
                "action_result": None,
                "needs_more_info": True,
            }

        # ── Exécuter l'action ──
        action_result = await self._execute_action(intent, state)

        return {
            "response": action_result.get("message", "Action traitée avec succès."),
            "documents": [],
            "action_result": action_result,
        }

    async def _execute_action(self, intent: str, state: ConversationState) -> dict:
        """Exécute l'action correspondant à l'intention."""
        # Collecter les valeurs des slots
        slot_values = {
            name: slot.value
            for name, slot in state.slots.items()
            if slot.filled and slot.value is not None
        }
        if state.business_id is not None:
            slot_values["business_id"] = str(state.business_id)
        if state.customer_id is not None:
            slot_values["customer_id"] = str(state.customer_id)
        if state.conversation_id is not None:
            slot_values["conversation_id"] = str(state.conversation_id)

        # Utiliser le registre d'actions si disponible
        if self.registry is not None:
            try:
                action = self.registry.get_action(intent)
                if action is not None:
                    result = await action.execute(slot_values)
                    logger.info(
                        "action_agent.executed",
                        intent=intent,
                        action=action.name,
                    )
                    return result
            except Exception as e:
                logger.error(
                    "action_agent.execution_error",
                    intent=intent,
                    error=str(e),
                )
                return {
                    "success": False,
                    "message": "Une erreur est survenue lors du traitement.",
                    "error": str(e),
                }

        # Fallback : simuler l'action
        logger.info("action_agent.simulated", intent=intent, slots=slot_values)
        return {
            "success": True,
            "message": f"Action '{intent}' traitée.",
            "data": slot_values,
        }
