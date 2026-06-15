"""Factory du moteur conversationnel Jenny.

Construit un `ConversationEngine` totalement câblé :
- provider LLM (depuis Settings, fallback templates si absent)
- registre d'actions (devis, paiement, RDV, ticket, planning, commande)
- agents (faq, action, planning, payment, quote, fallback, escalation)
- routeur d'agents
- générateur de réponses (LLM)

Utilisé par toutes les routes (`/conversation/chat`, webhooks…) afin de
garantir un comportement cohérent et configurable depuis le `.env`.
"""

from __future__ import annotations

from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.actions.handlers.check_planning import CheckPlanningAction
from jenny.actions.handlers.create_ticket import CreateTicketAction
from jenny.actions.handlers.generate_quote import GenerateQuoteAction
from jenny.actions.handlers.join_waitlist import JoinWaitlistAction
from jenny.actions.handlers.manage_appointment import ManageAppointmentAction
from jenny.actions.handlers.order_check import CheckOrderAction
from jenny.actions.handlers.process_payment import ProcessPaymentAction
from jenny.actions.handlers.set_customer_name import SetCustomerNameAction
from jenny.actions.registry import ActionRegistry
from jenny.agents.action_agent import ActionAgent
from jenny.agents.fallback_agent import FallbackAgent
from jenny.agents.faq_agent import FAQAgent
from jenny.agents.payment_agent import PaymentAgent
from jenny.agents.planning_agent import PlanningAgent
from jenny.agents.quote_agent import QuoteAgent
from jenny.agents.router import AgentRouter
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.engine.conversation_engine import ConversationEngine
from jenny.engine.response_generator import ResponseGenerator
from jenny.engine.state_manager import StateManager
from jenny.integrations.google_calendar import GoogleCalendarService
from jenny.llm.providers import BaseLLMProvider, get_default_llm_provider
from jenny.rag.embeddings import get_default_embedder
from jenny.rag.retriever import VectorRetriever
from jenny.rag.vector_store import PgVectorStore

logger = get_logger(__name__)


def build_retriever() -> VectorRetriever:
    """Construit le retriever RAG (embeddings configurés + pgvector).

    L'embedder et le store sont instanciés sans I/O ; la session DB est
    ouverte à la demande lors de chaque recherche.
    """
    embedder = get_default_embedder()
    store = PgVectorStore(embedding_dim=embedder.dimension)
    return VectorRetriever(embedder=embedder, vector_store=store)


def load_ml_predictors() -> tuple[object | None, object | None]:
    """Charge les prédicteurs Intent/NER depuis les checkpoints entraînés.

    Tolérant aux pannes : si les checkpoints sont absents ou si torch n'est
    pas disponible, renvoie (None, None) et le moteur bascule sur les règles.
    """
    settings = get_settings()
    if not settings.enable_ml_models:
        return None, None

    intent_predictor: object | None = None
    ner_predictor: object | None = None

    try:
        from ml.models.intent.predict import IntentPredictor

        intent_predictor = IntentPredictor.from_checkpoint(settings.intent_model_path)
        logger.info("engine.ml.intent_loaded", path=settings.intent_model_path)
    except Exception as e:
        logger.warning("engine.ml.intent_unavailable", error=str(e))

    try:
        from ml.models.ner.predict import NERPredictor

        ner_predictor = NERPredictor.from_checkpoint(settings.ner_model_path)
        logger.info("engine.ml.ner_loaded", path=settings.ner_model_path)
    except Exception as e:
        logger.warning("engine.ml.ner_unavailable", error=str(e))

    return intent_predictor, ner_predictor


def build_action_registry(
    calendar: GoogleCalendarService | None = None,
) -> ActionRegistry:
    """Enregistre toutes les actions métier disponibles."""
    registry = ActionRegistry()
    cal = calendar or GoogleCalendarService()

    registry.register(CheckOrderAction(), intents=["order_status"])
    registry.register(CheckPlanningAction(calendar_service=cal), intents=["planning"])
    # Réservation RÉELLE en base (catalogue + agenda) plutôt que simulée.
    registry.register(BookAppointmentDBAction(), intents=["appointment"])
    # Gestion par le client de son propre RDV (annuler / déplacer / confirmer).
    registry.register(ManageAppointmentAction(), intents=["manage_appointment"])
    # Inscription en liste d'attente quand le salon est complet (anti-no-show).
    registry.register(JoinWaitlistAction(), intents=["join_waitlist"])
    # Enregistrement du nom du client (après « c'est à quel nom ? »).
    registry.register(SetCustomerNameAction(), intents=["set_customer_name"])
    registry.register(CreateTicketAction(), intents=["complaint", "support"])
    registry.register(ProcessPaymentAction(), intents=["payment"])
    registry.register(GenerateQuoteAction(), intents=["quote"])

    return registry


def build_agent_router(
    registry: ActionRegistry,
    calendar: GoogleCalendarService | None = None,
) -> AgentRouter:
    """Enregistre les agents Jenny dans un AgentRouter."""
    cal = calendar or GoogleCalendarService()
    router = AgentRouter()

    router.register("fallback", FallbackAgent())
    router.register("faq", FAQAgent(retriever=build_retriever()))
    router.register("action", ActionAgent(action_registry=registry))
    router.register("planning", PlanningAgent(action_registry=registry, calendar_service=cal))
    router.register("payment", PaymentAgent(action_registry=registry))
    router.register("quote", QuoteAgent(action_registry=registry))

    return router


def build_engine(
    *,
    llm_provider: BaseLLMProvider | None = None,
    state_manager: StateManager | None = None,
    calendar: GoogleCalendarService | None = None,
) -> ConversationEngine:
    """Construit un `ConversationEngine` prêt à l'emploi.

    Args:
        llm_provider: provider LLM à utiliser. Si None, lecture des Settings.
        state_manager: gestionnaire d'état partagé (Redis si dispo).
        calendar: service Google Calendar (réel ou simulé).

    Returns:
        Un moteur entièrement câblé. Si le LLM n'est pas configuré,
        il bascule sur des templates pour ne pas casser l'expérience.
    """
    cal = calendar or GoogleCalendarService()
    sm = state_manager or StateManager()

    registry = build_action_registry(calendar=cal)
    router = build_agent_router(registry, calendar=cal)

    provider = llm_provider if llm_provider is not None else get_default_llm_provider()
    response_generator = ResponseGenerator(provider) if provider is not None else None

    intent_predictor, ner_predictor = load_ml_predictors()

    engine = ConversationEngine(
        state_manager=sm,
        intent_predictor=intent_predictor,
        ner_predictor=ner_predictor,
        agent_router=router,
        response_generator=response_generator,
    )

    logger.info(
        "engine.factory.ready",
        llm=provider.model_name if provider is not None else "templates",
        ml_intent=intent_predictor is not None,
        ml_ner=ner_predictor is not None,
        agents=["faq", "action", "planning", "payment", "quote", "fallback"],
        actions=[a["name"] for a in registry.list_actions()],
    )
    return engine


# ── Singleton partagé entre les routes (reset possible pour les tests) ──

_engine_singleton: ConversationEngine | None = None


def get_engine() -> ConversationEngine:
    """Renvoie le moteur partagé (lazy init via `build_engine`)."""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = build_engine()
    return _engine_singleton


def reset_engine() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _engine_singleton
    _engine_singleton = None
