"""Agent Paiement — Gestion des paiements et factures.

Gère les demandes liées au paiement :
- Moyens de paiement acceptés
- Suivi de facturation
- Paiement en plusieurs fois
- Problèmes de paiement
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.actions.registry import ActionRegistry
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)


class PaymentAgent:
    """Agent spécialisé dans les paiements et la facturation."""

    name: str = "payment"

    def __init__(
        self,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.registry = action_registry

    async def handle(self, state: ConversationState) -> dict:
        """Traite une demande liée au paiement.

        Args:
            state: État de la conversation.

        Returns:
            Informations de paiement et instructions.
        """
        logger.info("payment_agent.handling", intent=state.current_intent)

        # Chercher des infos dans les slots
        order_number = None
        amount = None
        for slot_name, slot in state.slots.items():
            if slot.filled:
                if slot_name == "order_number":
                    order_number = slot.value
                elif slot_name == "amount":
                    amount = slot.value

        # Exécuter via le registre si disponible
        if self.registry is not None:
            action = self.registry.get_action("payment")
            if action is not None:
                try:
                    result = await action.execute(
                        {
                            "order_number": order_number,
                            "amount": amount,
                        }
                    )
                    return {
                        "response": result.get("message", "Paiement traité."),
                        "documents": [],
                        "action_result": result,
                    }
                except Exception as e:
                    logger.error("payment_agent.action_error", error=str(e))

        # Réponse par défaut avec les moyens de paiement
        payment_info = (
            "Nous acceptons les moyens de paiement suivants :\n"
            "• Carte bancaire (Visa, Mastercard)\n"
            "• Virement bancaire\n"
            "• PayPal\n"
            "• Paiement en 3x sans frais (à partir de 100€)\n\n"
        )

        if order_number:
            payment_info += f"Pour la commande {order_number}, "
            payment_info += "vous pouvez régler directement depuis votre espace client."
        else:
            payment_info += (
                "Souhaitez-vous effectuer un paiement ? Précisez votre numéro de commande."
            )

        return {
            "response": payment_info,
            "documents": [],
            "action_result": {
                "success": True,
                "type": "payment_info",
                "order_number": order_number,
            },
        }
