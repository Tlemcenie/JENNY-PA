"""Répartiteur d'agents — Route les messages vers l'agent approprié.

Le routeur analyse l'intention détectée et l'historique
de la conversation pour choisir le meilleur agent :

- FAQAgent : questions générales, recherche documentaire (RAG)
- ActionAgent : commandes, réservations, vérifications
- FallbackAgent : quand aucun agent spécialisé ne convient
- Escalation : transfert vers un humain

Le routeur peut aussi combiner plusieurs agents
pour des requêtes complexes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState

logger = get_logger(__name__)


class Agent(Protocol):
    """Interface qu'un agent doit respecter."""

    name: str

    async def handle(self, state: ConversationState) -> dict:
        """Traite la demande et retourne un résultat.

        Returns:
            {"agent": str, "response": str, "documents": list, "action_result": dict|None}
        """
        ...


# ── Mapping intention → agent ──

INTENT_AGENT_MAP: dict[str, str] = {
    "greeting": "fallback",
    "closing": "fallback",
    "general": "fallback",
    "small_talk": "fallback",
    "order_status": "action",
    "pricing": "faq",
    "appointment": "action",
    "manage_appointment": "action",
    "join_waitlist": "action",
    "set_customer_name": "action",
    "complaint": "faq",
    "faq": "faq",
    "escalation": "escalation",
    "payment": "payment",
    "payment_question": "payment",
    "quote": "quote",
    "planning": "planning",
}


class AgentRouter:
    """Route les messages vers l'agent le plus adapté.

    Sélectionne un agent en fonction de :
    1. L'intention détectée
    2. La confiance de la détection
    3. Le contexte de la conversation
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, name: str, agent: Agent) -> None:
        """Enregistre un agent dans le routeur."""
        self._agents[name] = agent
        logger.info("router.register", agent=name)

    async def route(self, state: ConversationState) -> dict:
        """Route vers l'agent approprié.

        Args:
            state: État de la conversation avec intention détectée.

        Returns:
            Résultat de l'agent sélectionné.
        """
        intent = state.current_intent or "general"
        confidence = state.intent_confidence

        # Si la confiance est trop basse, utiliser le fallback
        if confidence < 0.4:
            agent_name = "fallback"
            logger.info(
                "router.low_confidence",
                intent=intent,
                confidence=f"{confidence:.2f}",
            )
        else:
            agent_name = INTENT_AGENT_MAP.get(intent, "fallback")

        # Cas spécial : escalation
        if intent == "escalation":
            return {
                "agent": "escalation",
                "response": "Je vous transfère vers un conseiller.",
                "documents": [],
                "action_result": None,
                "requires_human": True,
            }

        # Exécuter l'agent
        agent = self._agents.get(agent_name)
        if agent is None:
            logger.warning("router.agent_not_found", agent=agent_name)
            return {
                "agent": "fallback",
                "response": "Je vais traiter votre demande.",
                "documents": [],
                "action_result": None,
            }

        logger.info("router.dispatching", agent=agent_name, intent=intent)

        try:
            result = await agent.handle(state)
            result["agent"] = agent_name
            return result
        except Exception as e:
            logger.error("router.agent_error", agent=agent_name, error=str(e))
            return {
                "agent": "fallback",
                "response": "Une erreur est survenue. Veuillez réessayer.",
                "documents": [],
                "action_result": None,
            }
