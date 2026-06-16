"""Agent Devis — Génération et gestion de devis.

Gère les demandes de devis :
- Création de devis personnalisé
- Suivi de devis existant
- Envoi de devis par email
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.actions.registry import ActionRegistry
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)


class QuoteAgent:
    """Agent spécialisé dans la génération de devis."""

    name: str = "quote"

    def __init__(
        self,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.registry = action_registry

    async def handle(self, state: ConversationState) -> dict:
        """Traite une demande de devis.

        Collecte les informations nécessaires et génère un devis.

        Args:
            state: État de la conversation.

        Returns:
            Devis généré ou demande d'informations complémentaires.
        """
        logger.info("quote_agent.handling", intent=state.current_intent)

        # Collecter les infos disponibles + injecter le CONTEXTE (comme ActionAgent)
        # pour que l'action puisse persister un VRAI devis (business, client).
        params: dict[str, str] = {}
        for slot_name, slot in state.slots.items():
            if slot.filled and slot.value:
                params[slot_name] = slot.value
        if state.business_id is not None:
            params["business_id"] = str(state.business_id)
        if state.customer_id is not None:
            params["customer_id"] = str(state.customer_id)
        if state.conversation_id is not None:
            params["conversation_id"] = str(state.conversation_id)

        # Prestation demandée : slot service/product, sinon dernier message client.
        if not params.get("service") and not params.get("product"):
            last_user = next(
                (
                    m.get("content", "")
                    for m in reversed(state.message_history)
                    if m.get("role") == "user"
                ),
                "",
            )
            if last_user:
                params["service"] = last_user

        # Exécuter le VRAI devis via le registre.
        if self.registry is not None:
            action = self.registry.get_action("quote")
            if action is not None:
                try:
                    result = await action.execute(params)
                    if not result.get("success") and result.get("needs_service"):
                        cat = result.get("catalogue")
                        resp = "Avec plaisir ! Pour quel service souhaitez-vous un devis ?"
                        if cat:
                            resp += f"\n\n{cat}"
                        return {"response": resp, "documents": [], "action_result": result}
                    return {
                        "response": result.get("message", "Votre devis est en préparation."),
                        "documents": [],
                        "action_result": result,
                    }
                except Exception as e:
                    logger.error("quote_agent.action_error", error=str(e))

        # Repli (registre indisponible) : on demande la prestation.
        return {
            "response": "Je peux vous préparer un devis. Quel service vous intéresse ?",
            "documents": [],
            "action_result": {"success": False, "type": "quote_request"},
        }
