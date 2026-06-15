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

        # Collecter les infos disponibles
        collected_info: dict[str, str | None] = {}
        for slot_name, slot in state.slots.items():
            if slot.filled and slot.value:
                collected_info[slot_name] = slot.value

        # Exécuter via le registre si disponible
        if self.registry is not None:
            action = self.registry.get_action("quote")
            if action is not None:
                try:
                    result = await action.execute(collected_info)
                    return {
                        "response": result.get("message", "Devis en cours de création."),
                        "documents": [],
                        "action_result": result,
                    }
                except Exception as e:
                    logger.error("quote_agent.action_error", error=str(e))

        # Vérifier quelles infos manquent
        has_email = "email" in collected_info
        has_name = "name" in collected_info
        has_product = "product" in collected_info

        if not has_product and not has_name:
            response = (
                "Je peux vous préparer un devis personnalisé ! "
                "Pour cela, j'aurais besoin de :\n"
                "• La prestation ou le produit souhaité\n"
                "• Votre nom\n"
                "• Votre email pour l'envoi du devis\n\n"
                "Quel service vous intéresse ?"
            )
        elif has_product and not has_email:
            product = collected_info.get("product", "votre demande")
            response = (
                f"Parfait, je prépare un devis pour {product}. "
                "À quelle adresse email souhaitez-vous le recevoir ?"
            )
        else:
            email = collected_info.get("email", "votre email")
            response = (
                "Votre demande de devis a été enregistrée. "
                f"Vous recevrez le devis à {email} sous 24h. "
                "Un conseiller vous contactera si besoin."
            )

        return {
            "response": response,
            "documents": [],
            "action_result": {
                "success": True,
                "type": "quote_request",
                "collected_info": collected_info,
            },
        }
