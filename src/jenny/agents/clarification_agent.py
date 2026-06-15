"""Agent de Clarification — Jenny repose une question quand elle n'est pas sûre.

Quand la confiance de détection d'intention est trop basse,
ou que le message est ambigu, cet agent génère une question
ciblée pour mieux comprendre la demande du client.

Exemples :
- Confiance < 50% → "Je ne suis pas sûre d'avoir compris. Vous souhaitez … ?"
- Multi-intent ambigu → "J'ai compris que vous vouliez X et Y, c'est bien ça ?"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)

# ── Mapping intent → description en français ──
INTENT_DESCRIPTIONS: dict[str, str] = {
    "greeting": "dire bonjour",
    "closing": "terminer la conversation",
    "order_status": "suivre une commande",
    "pricing": "connaître nos tarifs",
    "appointment": "prendre un rendez-vous",
    "complaint": "signaler un problème",
    "faq": "poser une question",
    "escalation": "parler à un conseiller",
    "payment": "effectuer un paiement",
    "quote": "demander un devis",
    "planning": "consulter les disponibilités",
    "general": "obtenir des informations",
}


class ClarificationAgent:
    """Agent qui génère des questions de clarification.

    Utilisé quand Jenny n'est pas suffisamment sûre de l'intention
    du client ou quand le message est ambigu.
    """

    name: str = "clarification"

    def generate_clarification(
        self,
        message: str,
        detected_intents: list[dict],
        confidence: float,
        entities: dict | None = None,
    ) -> str:
        """Génère une question de clarification contextuelle.

        Args:
            message: Le message original du client.
            detected_intents: Liste des intentions détectées avec leur confiance.
            confidence: Confiance de l'intention principale.
            entities: Entités extraites du message.

        Returns:
            Texte de la question de clarification.
        """
        logger.info(
            "clarification_agent.generating",
            confidence=f"{confidence:.0%}",
            detected_count=len(detected_intents),
            intents=[d["intent"] for d in detected_intents],
        )

        # Cas 1 : Confiance très basse — on n'a rien compris
        if confidence < 0.3:
            return self._very_low_confidence(message)

        # Cas 2 : Confiance basse — on a une vague idée
        if confidence < 0.5:
            return self._low_confidence(detected_intents)

        # Cas 3 : Plusieurs intents proches — on a besoin de prioriser
        if len(detected_intents) >= 2:
            return self._ambiguous_multi_intent(detected_intents)

        # Cas 4 : Fallback de clarification
        return self._generic_clarification()

    def _very_low_confidence(self, message: str) -> str:
        """Confiance < 30% : on comprend très mal."""
        return (
            "🤔 Je ne suis pas sûre d'avoir bien compris votre demande.\n\n"
            "Pourriez-vous reformuler ? Je peux vous aider avec :\n"
            "• 📅 **Rendez-vous** — prendre ou modifier un RDV\n"
            "• 💰 **Tarifs & devis** — connaître nos prix\n"
            "• 📦 **Suivi commande** — vérifier l'état d'une commande\n"
            "• ❓ **Question** — poser une question sur nos services\n\n"
            "Dites-moi comment je peux vous aider ! 😊"
        )

    def _low_confidence(self, detected_intents: list[dict]) -> str:
        """Confiance 30-50% : on a une vague idée."""
        if not detected_intents:
            return self._very_low_confidence("")

        top = detected_intents[0]
        intent_desc = INTENT_DESCRIPTIONS.get(top["intent"], "vous aider")

        response = f"🤔 Si j'ai bien compris, vous souhaitez **{intent_desc}** ?\n\n"

        if len(detected_intents) > 1:
            other_descs = [
                INTENT_DESCRIPTIONS.get(d["intent"], d["intent"]) for d in detected_intents[1:3]
            ]
            alternatives = " ou ".join(f"**{d}**" for d in other_descs)
            response += f"Ou peut-être plutôt {alternatives} ?\n\n"

        response += "Précisez-moi et je m'en occupe tout de suite ! 😊"
        return response

    def _ambiguous_multi_intent(self, detected_intents: list[dict]) -> str:
        """Plusieurs intentions fortes détectées — on confirme."""
        descs = []
        for di in detected_intents[:3]:
            desc = INTENT_DESCRIPTIONS.get(di["intent"], di["intent"])
            descs.append(f"**{desc}**")

        intent_list = " et ".join(descs)

        return (
            f"👋 J'ai bien noté ! Vous souhaitez {intent_list}.\n\n"
            "C'est bien ça ? Je peux m'occuper de tout, "
            "ou souhaitez-vous qu'on commence par un point en particulier ?"
        )

    def _generic_clarification(self) -> str:
        """Clarification générique."""
        return (
            "🤔 Pourriez-vous préciser votre demande ?\n\n"
            "Je veux m'assurer de bien vous répondre. "
            "N'hésitez pas à détailler ce dont vous avez besoin ! 😊"
        )

    async def handle(self, state: ConversationState) -> dict:
        """Interface standard d'agent — pour compatibilité.

        Args:
            state: État de la conversation.

        Returns:
            Résultat avec la question de clarification.
        """
        # Extraire les intents depuis le contexte
        detected_intents = []
        if state.current_intent:
            detected_intents.append(
                {
                    "intent": state.current_intent,
                    "confidence": state.intent_confidence,
                }
            )

        message = ""
        if state.message_history:
            last_msg = state.message_history[-1]
            if last_msg.get("role") == "user":
                message = last_msg.get("content", "")

        response = self.generate_clarification(
            message=message,
            detected_intents=detected_intents,
            confidence=state.intent_confidence,
            entities={k: v.value for k, v in state.slots.items() if v.filled},
        )

        return {
            "response": response,
            "documents": [],
            "action_result": {
                "type": "clarification",
                "needs_clarification": True,
            },
        }
