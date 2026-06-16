"""Compat — ancien point d'entrée « graphe » branché sur le VRAI moteur.

Historiquement, ce module portait une orchestration LangGraph (StateGraph). Elle
était un **doublon jamais utilisé en production** : tout le runtime (chat,
webhooks, co-pilote) passe par ``jenny.engine.conversation_engine`` via
``jenny.engine.factory.get_engine``.

Pour supprimer la dette LangChain (dépendances ``langgraph``/``langchain-*``
embarquées pour rien) tout en gardant les tests historiques verts, on ne conserve
que la fonction publique ``process_message_with_graph`` — désormais une simple
façade au-dessus du moteur réel. Plus aucune dépendance LangChain.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from jenny.core.logging import get_logger
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import get_engine

logger = get_logger(__name__)

# Priorité dérivée de l'intention (les messages négatifs/escalades passent devant).
_MED_PRIORITY_INTENTS = frozenset({"payment", "appointment", "manage_appointment"})


def _as_uuid(value: str | None) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return uuid4()


async def process_message_with_graph(
    message: str,
    channel: str = "",
    sender: str = "",
    conversation_id: str | None = None,
    business_id: str | None = None,
) -> dict:
    """Traite un message via le VRAI moteur (façade de compatibilité).

    Conserve la forme de retour historique (``intent``, ``response``,
    ``priority``…) pour ne pas casser les tests, mais exécute la même
    orchestration que la production (intent ML → NER → agent → LLM).
    """
    engine = get_engine()
    result = await engine.process(
        EngineRequest(
            conversation_id=_as_uuid(conversation_id),
            business_id=_as_uuid(business_id),
            message_text=message,
            channel=channel or "",
        )
    )

    intent = result.intent
    requires_human = result.requires_human
    if requires_human or intent == "escalation":
        priority = 8
    elif intent == "complaint":
        priority = 7
    elif intent in _MED_PRIORITY_INTENTS:
        priority = 5
    else:
        priority = 3

    return {
        "intent": intent,
        "intent_confidence": result.intent_confidence,
        "detected_intents": result.detected_intents or [],
        "is_multi_intent": result.is_multi_intent,
        "needs_clarification": result.needs_clarification,
        "entities": result.entities or {},
        "agent": result.agent_used,
        "agent_names": [result.agent_used] if result.agent_used else [],
        "response": result.response_text,
        "requires_human": requires_human,
        "action_result": result.action_result,
        "priority": priority,
    }
