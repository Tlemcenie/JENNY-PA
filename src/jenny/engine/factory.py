"""fabrique le moteur conversationnel."""

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
from jenny.actions.handlers.set_customer_phone import SetCustomerPhoneAction
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
    """construit le retriever rag."""
    embedder = get_default_embedder()
    store = PgVectorStore(embedding_dim=embedder.dimension)
    return VectorRetriever(embedder=embedder, vector_store=store)


def load_ml_predictors() -> tuple[object | None, object | None]:
    """charge les modèles ml."""
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
    """enregistre les actions métier."""
    registry = ActionRegistry()

    registry.register(CheckOrderAction(), intents=["order_status"])
    # vraies dispos en base
    registry.register(CheckPlanningAction(), intents=["planning"])
    # vraie résa en base
    registry.register(BookAppointmentDBAction(), intents=["appointment"])
    # gère le rdv client
    registry.register(ManageAppointmentAction(), intents=["manage_appointment"])
    # liste d'attente si complet
    registry.register(JoinWaitlistAction(), intents=["join_waitlist"])
    # enregistre le nom
    registry.register(SetCustomerNameAction(), intents=["set_customer_name"])
    registry.register(SetCustomerPhoneAction(), intents=["set_customer_phone"])
    registry.register(CreateTicketAction(), intents=["complaint", "support"])
    registry.register(ProcessPaymentAction(), intents=["payment"])
    registry.register(GenerateQuoteAction(), intents=["quote"])

    return registry


def build_agent_router(
    registry: ActionRegistry,
    calendar: GoogleCalendarService | None = None,
    retriever: VectorRetriever | None = None,
) -> AgentRouter:
    """branche les agents."""
    cal = calendar or GoogleCalendarService()
    router = AgentRouter()

    router.register("fallback", FallbackAgent())
    router.register("faq", FAQAgent(retriever=retriever or build_retriever()))
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
    """construit un moteur complet."""
    cal = calendar or GoogleCalendarService()
    sm = state_manager or StateManager()

    registry = build_action_registry(calendar=cal)
    # retriever partagé
    retriever = build_retriever()
    router = build_agent_router(registry, calendar=cal, retriever=retriever)

    provider = llm_provider if llm_provider is not None else get_default_llm_provider()
    response_generator = ResponseGenerator(provider) if provider is not None else None

    intent_predictor, ner_predictor = load_ml_predictors()

    engine = ConversationEngine(
        state_manager=sm,
        intent_predictor=intent_predictor,
        ner_predictor=ner_predictor,
        agent_router=router,
        response_generator=response_generator,
        retriever=retriever,
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


# singleton partagé

_engine_singleton: ConversationEngine | None = None


def get_engine() -> ConversationEngine:
    """moteur partagé, lazy init."""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = build_engine()
    return _engine_singleton


def reset_engine() -> None:
    """reset pour les tests."""
    global _engine_singleton
    _engine_singleton = None
