"""fabrique le moteur conversationnel."""

from __future__ import annotations

import asyncio
import threading

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
from jenny.rag.embeddings import (
    SentenceTransformerEmbedder,
    adopt_st_model,
    get_default_embedder,
)
from jenny.rag.retriever import VectorRetriever
from jenny.rag.vector_store import PgVectorStore

logger = get_logger(__name__)


def build_retriever() -> VectorRetriever:
    """construit le retriever rag."""
    embedder = get_default_embedder()
    store = PgVectorStore(embedding_dim=embedder.dimension)
    return VectorRetriever(embedder=embedder, vector_store=store)


def rag_encoder() -> object | None:
    """mpnet du rag, si c'est le même."""
    from ml.models.intent_head.predict import ENCODER_NAME

    embedder = get_default_embedder()
    if not isinstance(embedder, SentenceTransformerEmbedder):
        return None
    if embedder.model_name.split("/")[-1] != ENCODER_NAME:
        return None
    # registre rag verrouillé
    return embedder._load_model()


def load_intent_predictor(kind: str | None = None, *, fallback: bool = True) -> object | None:
    """charge l'intention : head ou lstm."""
    settings = get_settings()
    kind = kind or settings.intent_model_kind

    if kind == "head":
        try:
            from ml.models.intent_head.predict import EmbeddingIntentPredictor

            # un seul mpnet en ram
            head = EmbeddingIntentPredictor.from_checkpoint(
                settings.intent_head_path, encoder=rag_encoder()
            )
            logger.info("engine.ml.intent_loaded", kind="head", path=settings.intent_head_path)
            return head
        except Exception as e:
            logger.warning("engine.ml.intent_head_unavailable", error=str(e))
            if not fallback:
                return None
        # repli sur le lstm

    try:
        from ml.models.intent.predict import IntentPredictor

        lstm = IntentPredictor.from_checkpoint(settings.intent_model_path)
        logger.info("engine.ml.intent_loaded", kind="lstm", path=settings.intent_model_path)
        return lstm
    except Exception as e:
        logger.warning("engine.ml.intent_unavailable", error=str(e))
        return None


def load_ner_predictor() -> object | None:
    """charge le ner bigru."""
    settings = get_settings()
    try:
        from ml.models.ner.predict import NERPredictor

        ner = NERPredictor.from_checkpoint(settings.ner_model_path)
        logger.info("engine.ml.ner_loaded", path=settings.ner_model_path)
        return ner
    except Exception as e:
        logger.warning("engine.ml.ner_unavailable", error=str(e))
        return None


def load_ml_predictors() -> tuple[object | None, object | None]:
    """charge les modèles ml."""
    settings = get_settings()
    if not settings.enable_ml_models:
        return None, None

    intent_predictor = load_intent_predictor()
    # le ner remplit service et date
    ner_predictor = load_ner_predictor() if settings.enable_ner_model else None
    return intent_predictor, ner_predictor


def share_encoder(retriever: VectorRetriever, intent_predictor: object | None) -> bool:
    """un seul mpnet en ram."""
    encoder = getattr(intent_predictor, "encoder", None)
    embedder = retriever.embedder
    if encoder is None or not isinstance(embedder, SentenceTransformerEmbedder):
        return False
    from ml.models.intent_head.predict import ENCODER_NAME

    if embedder.model_name.split("/")[-1] != ENCODER_NAME:
        return False
    # déjà le même objet
    if embedder._model is encoder:
        return True
    if embedder._model is not None:
        return False
    if not adopt_st_model(embedder.model_name, encoder):
        return False
    logger.info("engine.ml.encoder_shared", model=ENCODER_NAME)
    return True


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
    share_encoder(retriever, intent_predictor)

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
        ml_intent_kind=type(intent_predictor).__name__ if intent_predictor is not None else None,
        ml_ner=ner_predictor is not None,
        agents=["faq", "action", "planning", "payment", "quote", "fallback"],
        actions=[a["name"] for a in registry.list_actions()],
    )
    return engine


# singleton partagé

_engine_singleton: ConversationEngine | None = None
# une seule construction
_ENGINE_LOCK = threading.Lock()


def get_engine() -> ConversationEngine:
    """moteur partagé, construit une fois."""
    global _engine_singleton
    engine = _engine_singleton
    if engine is not None:
        return engine
    with _ENGINE_LOCK:
        if _engine_singleton is None:
            _engine_singleton = build_engine()
        return _engine_singleton


async def aget_engine() -> ConversationEngine:
    """moteur sans geler la boucle."""
    engine = _engine_singleton
    if engine is not None:
        return engine
    return await asyncio.to_thread(get_engine)


def reset_engine() -> None:
    """reset pour les tests."""
    global _engine_singleton
    with _ENGINE_LOCK:
        _engine_singleton = None
