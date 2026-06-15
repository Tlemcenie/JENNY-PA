"""Orchestration agentique avec LangGraph.

Graphe d'état complet pour le traitement intelligent
des messages clients : intent → NER → routing → agent → réponse.

Supporte :
- Multi-label : un message peut déclencher N agents
- Clarification : Jenny repose une question si la confiance est basse

Ce graphe utilise les vrais modèles ML entraînés
et les agents spécialisés de Jenny.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from langgraph.graph import END, StateGraph

from jenny.core.logging import get_logger

logger = get_logger(__name__)


# ── État du graphe ──


@dataclass
class MessageState:
    """État partagé entre les nœuds du graphe agent."""

    # Input
    message_content: str = ""
    channel: str = ""
    sender: str = ""
    conversation_id: str = ""
    business_id: str = ""

    # ML results — multi-label
    intent: str | None = None
    intent_confidence: float = 0.0
    detected_intents: list = field(default_factory=list)
    # ex: [{"intent": "appointment", "confidence": 0.85}, {"intent": "quote", "confidence": 0.72}]
    is_multi_intent: bool = False
    needs_clarification: bool = False
    entities: dict = field(default_factory=dict)

    # Routing
    category: str | None = None
    priority: int | None = None
    agent_name: str | None = None
    agent_names: list = field(default_factory=list)  # Multi-agent routing
    agent_response: str = ""

    # Output
    suggested_reply: str | None = None
    requires_human: bool = False
    action_result: dict = field(default_factory=dict)
    rag_documents: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ── Cache global pour les modèles ML ──
_intent_predictor = None
_ner_predictor = None


def _get_intent_predictor():
    """Charge le modèle intent une seule fois (singleton)."""
    global _intent_predictor
    if _intent_predictor is None:
        intent_path = Path("checkpoints/intent/best_model.pt")
        if intent_path.exists():
            from ml.models.intent.predict import IntentPredictor

            _intent_predictor = IntentPredictor.from_checkpoint(str(intent_path))
            logger.info("graph.intent_model.loaded")
    return _intent_predictor


def _get_ner_predictor():
    """Charge le modèle NER une seule fois (singleton)."""
    global _ner_predictor
    if _ner_predictor is None:
        ner_path = Path("checkpoints/ner/best_model.pt")
        if ner_path.exists():
            from ml.models.ner.predict import NERPredictor

            _ner_predictor = NERPredictor.from_checkpoint(str(ner_path))
            logger.info("graph.ner_model.loaded")
    return _ner_predictor


# ── Nœuds du graphe ──


async def detect_intent(state: MessageState) -> MessageState:
    """Détecte l'intention du message avec le modèle LSTM multi-label."""
    logger.info("graph.detect_intent", message=state.message_content[:50])

    predictor = _get_intent_predictor()
    if predictor is not None:
        # Utiliser predict_multi pour détecter N intentions
        result = predictor.predict_multi(state.message_content)

        state.detected_intents = result["intents"]
        state.intent = result["primary_intent"]
        state.intent_confidence = result["primary_confidence"]
        state.is_multi_intent = result["is_multi_intent"]
        state.needs_clarification = result["needs_clarification"]
    else:
        # Fallback sans modèle
        state.intent = "general"
        state.intent_confidence = 0.5
        state.detected_intents = [{"intent": "general", "confidence": 0.5}]
        state.is_multi_intent = False
        state.needs_clarification = False

    state.category = state.intent
    logger.info(
        "graph.intent_detected",
        intent=state.intent,
        confidence=f"{state.intent_confidence:.0%}",
        multi_intent=state.is_multi_intent,
        detected_count=len(state.detected_intents),
        needs_clarification=state.needs_clarification,
    )
    return state


async def extract_entities(state: MessageState) -> MessageState:
    """Extrait les entités avec le modèle BiGRU NER entraîné."""
    logger.info("graph.extract_entities")

    predictor = _get_ner_predictor()
    if predictor is not None:
        state.entities = predictor.predict(state.message_content)
    else:
        state.entities = {}

    logger.info("graph.entities_extracted", count=len(state.entities))
    return state


async def route_to_agent(state: MessageState) -> MessageState:
    """Route vers le(s) agent(s) approprié(s) — supporte multi-label."""
    from jenny.agents.router import INTENT_AGENT_MAP

    priority_map = {
        "complaint": 8,
        "escalation": 9,
        "order_status": 5,
        "payment": 6,
        "quote": 4,
        "appointment": 4,
        "planning": 3,
        "faq": 2,
        "pricing": 3,
        "greeting": 1,
        "closing": 1,
    }

    confidence = state.intent_confidence

    if confidence < 0.4:
        state.agent_name = "fallback"
        state.agent_names = ["fallback"]
    elif state.is_multi_intent and len(state.detected_intents) > 1:
        # Multi-label : router vers chaque agent détecté
        agents = []
        for di in state.detected_intents:
            agent = INTENT_AGENT_MAP.get(di["intent"], "fallback")
            if agent not in agents:
                agents.append(agent)
        state.agent_names = agents
        state.agent_name = agents[0]  # L'agent principal
    else:
        intent = state.intent or "general"
        state.agent_name = INTENT_AGENT_MAP.get(intent, "fallback")
        state.agent_names = [state.agent_name]

    # Priorité = max des intentions détectées
    max_priority = 0
    for di in state.detected_intents:
        p = priority_map.get(di["intent"], 3)
        if p > max_priority:
            max_priority = p
    state.priority = max_priority or priority_map.get(state.intent or "general", 3)

    logger.info(
        "graph.routed",
        agent=state.agent_name,
        agents=state.agent_names,
        priority=state.priority,
        multi=state.is_multi_intent,
    )
    return state


async def check_urgency(state: MessageState) -> MessageState:
    """Vérifie si le message est urgent et nécessite une intervention humaine."""
    if state.intent == "escalation" or (state.priority is not None and state.priority >= 8):
        state.requires_human = True
    elif state.intent_confidence < 0.3 and not state.needs_clarification:
        # Confiance très basse et pas de clarification possible → humain
        state.requires_human = True

    return state


def _instantiate_agent(agent_name: str):
    """Instancie un agent par son nom."""
    if agent_name == "faq":
        from jenny.agents.faq_agent import FAQAgent

        return FAQAgent()
    elif agent_name == "action":
        from jenny.agents.action_agent import ActionAgent

        return ActionAgent()
    elif agent_name == "payment":
        from jenny.agents.payment_agent import PaymentAgent

        return PaymentAgent()
    elif agent_name == "quote":
        from jenny.agents.quote_agent import QuoteAgent

        return QuoteAgent()
    elif agent_name == "planning":
        from jenny.agents.planning_agent import PlanningAgent
        from jenny.integrations.google_calendar import GoogleCalendarService

        calendar = GoogleCalendarService()
        return PlanningAgent(calendar_service=calendar)
    else:
        from jenny.agents.fallback_agent import FallbackAgent

        return FallbackAgent()


async def execute_agent(state: MessageState) -> MessageState:
    """Exécute le(s) agent(s) sélectionné(s) — supporte multi-agent."""
    agent_names = state.agent_names or [state.agent_name or "fallback"]
    logger.info("graph.execute_agent", agents=agent_names, multi=len(agent_names) > 1)

    from jenny.engine.state_manager import ConversationState

    all_responses = []
    combined_action_result = {}
    combined_documents = []

    for agent_name in agent_names:
        agent = _instantiate_agent(agent_name)

        # Trouver l'intent correspondant pour cet agent
        from jenny.agents.router import INTENT_AGENT_MAP

        agent_intent = state.intent or "general"
        for di in state.detected_intents:
            if INTENT_AGENT_MAP.get(di["intent"]) == agent_name:
                agent_intent = di["intent"]
                break

        # Créer un ConversationState pour l'agent
        conv_state = ConversationState()
        conv_state.set_intent(agent_intent, state.intent_confidence)
        conv_state.add_user_message(state.message_content)

        # Transférer les entités comme slots
        for entity_name, entity_value in state.entities.items():
            conv_state.set_slot(entity_name, entity_value)

        result = await agent.handle(conv_state)

        response_text = result.get("response", "")
        if response_text:
            all_responses.append(response_text)

        action_res = result.get("action_result")
        if action_res:
            combined_action_result[agent_name] = action_res

        docs = result.get("documents", [])
        combined_documents.extend(docs)

    # Composer la réponse finale
    if len(all_responses) > 1:
        state.agent_response = "\n\n---\n\n".join(all_responses)
    elif all_responses:
        state.agent_response = all_responses[0]
    else:
        state.agent_response = ""

    state.suggested_reply = state.agent_response
    state.action_result = (
        combined_action_result
        if len(agent_names) > 1
        else (combined_action_result.get(agent_names[0]) or {})
    )
    state.rag_documents = combined_documents

    return state


async def clarify(state: MessageState) -> MessageState:
    """Demande une clarification quand Jenny n'est pas sûre.

    Génère une question ciblée pour mieux comprendre l'intention du client.
    """
    logger.info(
        "graph.clarify",
        intent=state.intent,
        confidence=f"{state.intent_confidence:.0%}",
        detected_intents=[d["intent"] for d in state.detected_intents],
    )

    from jenny.agents.clarification_agent import ClarificationAgent

    agent = ClarificationAgent()

    response = agent.generate_clarification(
        message=state.message_content,
        detected_intents=state.detected_intents,
        confidence=state.intent_confidence,
        entities=state.entities,
    )

    state.agent_response = response
    state.suggested_reply = response
    state.agent_name = "clarification"
    state.metadata["clarification_reason"] = (
        "low_confidence" if state.intent_confidence < 0.5 else "ambiguous_intents"
    )

    return state


async def escalate_to_human(state: MessageState) -> MessageState:
    """Escalade le message pour traitement humain."""
    logger.info("graph.escalate", sender=state.sender, intent=state.intent)
    state.suggested_reply = (
        "Je comprends votre demande. Je vous transfère vers un conseiller "
        "humain qui pourra mieux vous aider. Un instant s'il vous plaît."
    )
    state.requires_human = True
    return state


# ── Routing conditionnel ──


def should_escalate_or_clarify(
    state: MessageState,
) -> Literal["escalate", "clarify", "execute"]:
    """Détermine si on escalade, clarifie ou exécute.

    Ordre de priorité :
    1. Escalade → humain (urgent / explicitement demandé)
    2. Clarification → Jenny repose une question (confiance basse)
    3. Exécution → agent(s) spécialisé(s)
    """
    if state.requires_human:
        return "escalate"
    if state.needs_clarification:
        return "clarify"
    return "execute"


# ── Construction du graphe ──


def build_message_agent() -> StateGraph:
    """Construit le graphe d'agent complet pour le traitement des messages.

    Flux :
      detect_intent → extract_entities → route_to_agent → check_urgency
        → [escalate | clarify | execute_agent] → END
    """
    graph = StateGraph(MessageState)

    # Ajout des nœuds
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("route_to_agent", route_to_agent)
    graph.add_node("check_urgency", check_urgency)
    graph.add_node("execute_agent", execute_agent)
    graph.add_node("clarify", clarify)
    graph.add_node("escalate", escalate_to_human)

    # Définition du flux
    graph.set_entry_point("detect_intent")
    graph.add_edge("detect_intent", "extract_entities")
    graph.add_edge("extract_entities", "route_to_agent")
    graph.add_edge("route_to_agent", "check_urgency")
    graph.add_conditional_edges(
        "check_urgency",
        should_escalate_or_clarify,
        {
            "escalate": "escalate",
            "clarify": "clarify",
            "execute": "execute_agent",
        },
    )
    graph.add_edge("execute_agent", END)
    graph.add_edge("clarify", END)
    graph.add_edge("escalate", END)

    return graph


async def process_message_with_graph(
    message: str,
    channel: str = "",
    sender: str = "",
    conversation_id: str | None = None,
    business_id: str | None = None,
) -> dict:
    """Point d'entrée simplifié pour traiter un message via le graphe LangGraph.

    Args:
        message: Texte du message client.
        channel: Canal d'origine (instagram, whatsapp, etc.).
        sender: Identifiant de l'expéditeur.
        conversation_id: ID de la conversation.
        business_id: ID du business.

    Returns:
        Résultat complet du traitement.
    """
    graph = build_message_agent()
    app = graph.compile()

    initial_state = MessageState(
        message_content=message,
        channel=channel,
        sender=sender,
        conversation_id=conversation_id or str(uuid4()),
        business_id=business_id or str(uuid4()),
    )

    result = await app.ainvoke(initial_state)

    # Le résultat peut être un dict ou un objet selon la version de langgraph
    def _get(key, default=None):
        if isinstance(result, dict):
            return result.get(key, default)
        return getattr(result, key, default)

    return {
        "intent": _get("intent"),
        "intent_confidence": _get("intent_confidence", 0.0),
        "detected_intents": _get("detected_intents", []),
        "is_multi_intent": _get("is_multi_intent", False),
        "needs_clarification": _get("needs_clarification", False),
        "entities": _get("entities", {}),
        "agent": _get("agent_name"),
        "agent_names": _get("agent_names", []),
        "response": _get("suggested_reply"),
        "requires_human": _get("requires_human", False),
        "action_result": _get("action_result"),
        "priority": _get("priority", 0),
    }
