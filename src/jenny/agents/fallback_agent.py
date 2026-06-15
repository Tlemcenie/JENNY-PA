"""Agent Fallback — Gestion des cas non couverts.

Agent par défaut quand aucun agent spécialisé ne convient :
- Confiance d'intention trop basse
- Intention non mappée à un agent
- Messages hors scope

Fournit une réponse générique et polie, et peut
proposer des suggestions pour guider l'utilisateur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)


class FallbackAgent:
    """Agent de fallback pour les cas non couverts."""

    name: str = "fallback"

    async def handle(self, state: ConversationState) -> dict:
        """Gère les cas non couverts par les agents spécialisés.

        Args:
            state: État de la conversation.

        Returns:
            Réponse générique avec suggestions.
        """
        intent = state.current_intent
        confidence = state.intent_confidence

        logger.info(
            "fallback_agent.handling",
            intent=intent,
            confidence=f"{confidence:.2f}",
        )

        # Réponses par contexte
        if intent == "greeting":
            response = (
                "Bonjour ! 👋 Je suis Jenny, votre assistant. "
                "Comment puis-je vous aider ?\n\n"
                "Je peux vous aider avec :\n"
                "• Le suivi de vos commandes\n"
                "• Nos tarifs et devis\n"
                "• La prise de rendez-vous\n"
                "• Vos questions fréquentes"
            )
        elif intent == "small_talk":
            response = "Ça va bien merci ! 😊 Et vous, comment puis-je vous aider aujourd'hui ?"
        elif intent == "closing":
            response = (
                "Merci pour votre confiance ! 😊 "
                "N'hésitez pas à revenir si vous avez d'autres questions. "
                "Bonne journée !"
            )
        elif confidence < 0.4:
            response = (
                "Je ne suis pas sûr d'avoir bien compris votre demande. "
                "Pourriez-vous reformuler ? "
                "Ou souhaitez-vous parler à un conseiller ?"
            )
        else:
            response = "Merci pour votre message. Je vais faire de mon mieux pour vous aider."

        return {
            "response": response,
            "documents": [],
            "action_result": None,
        }
