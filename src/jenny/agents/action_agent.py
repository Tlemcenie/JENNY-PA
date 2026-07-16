"""agent qui exécute les actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.engine.state_manager import ConversationPhase, ConversationState

if TYPE_CHECKING:
    from jenny.actions.registry import ActionRegistry

logger = get_logger(__name__)


# slots requis par intention
REQUIRED_SLOTS: dict[str, list[str]] = {
    "order_status": ["order_number"],
    # prestation + jour suffisent
    "appointment": ["service", "date"],
    # l'action gère les manques
    "manage_appointment": [],
    # rien de bloquant
    "join_waitlist": [],
    # nom déjà dans le slot
    "set_customer_name": [],
    "set_customer_phone": [],
    "complaint": [],  # rien de requis
}


class ActionAgent:
    """exécute les actions externes."""

    name: str = "action"

    def __init__(
        self,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.registry = action_registry

    async def handle(self, state: ConversationState) -> dict:
        """traite une demande d'action."""
        intent = state.current_intent or "general"

        # vérifie les slots requis
        required = REQUIRED_SLOTS.get(intent, [])
        for slot_name in required:
            if slot_name not in state.slots or not state.slots[slot_name].filled:
                # marque le slot requis
                from jenny.engine.state_manager import ExtractedSlot

                if slot_name not in state.slots:
                    state.slots[slot_name] = ExtractedSlot(name=slot_name, required=True)
                else:
                    state.slots[slot_name].required = True
                state.phase = ConversationPhase.SLOT_FILLING

        # le moteur demandera
        if state.has_missing_required_slots():
            return {
                "response": "J'ai besoin de plus d'informations.",
                "documents": [],
                "action_result": None,
                "needs_more_info": True,
            }

        # exécute l'action
        action_result = await self._execute_action(intent, state)

        return {
            "response": action_result.get("message", "Action traitée avec succès."),
            "documents": [],
            "action_result": action_result,
        }

    async def _execute_action(self, intent: str, state: ConversationState) -> dict:
        """lance la bonne action."""
        # valeurs des slots
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

        # registre si dispo
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

        # fallback : simulation
        logger.info("action_agent.simulated", intent=intent, slots=slot_values)
        return {
            "success": True,
            "message": f"Action '{intent}' traitée.",
            "data": slot_values,
        }
