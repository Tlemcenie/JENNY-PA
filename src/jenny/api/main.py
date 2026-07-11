"""Point d'entrée principal de l'API FastAPI Jenny.

Lance l'application, configure le lifespan (startup/shutdown),
et enregistre les routes.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jenny.api.middleware.observability import CorrelationIdMiddleware
from jenny.api.middleware.rate_limit import RateLimitMiddleware
from jenny.api.middleware.security import AuthContextMiddleware
from jenny.api.routes import (
    admin,
    api_keys,
    appointments,
    audit,
    auth,
    business,
    canned_responses,
    channels,
    conversation,
    conversations,
    copilot,
    customer_privacy,
    customers,
    feedback,
    health,
    ingest,
    insights,
    jenny_metrics,
    knowledge,
    knowledge_gaps,
    llm_settings,
    messages,
    metrics,
    nanogpt,
    notifications,
    owner_chat,
    payment_webhooks,
    pending_questions,
    prestations,
    public_booking,
    realtime,
    salon_extras,
    salon_stats,
    search,
    webhooks,
)
from jenny.core.config import get_settings
from jenny.core.logging import get_logger, setup_logging
from jenny.core.otel import instrument_fastapi_if_configured
from jenny.core.rate_limit import close_rate_limit_redis
from jenny.workers.queue import close_arq_pool

logger = get_logger(__name__)


async def _warmup_models() -> None:
    """Précharge LLM local et embedder RAG au démarrage (tâche de fond).

    Évite le cold-start sur le PREMIER message reçu (WhatsApp, etc.) : le modèle
    est déjà chargé en mémoire, la réponse part « au tac au tac ». Deux cas
    indépendants :
    - LLM Ollama : uniquement pour le provider « llama » (sans objet Groq/OpenAI) ;
    - embedder RAG : le sentence-transformer (défaut, in-process) met plusieurs
      secondes à charger torch + poids → à chauffer QUEL QUE SOIT le provider
      LLM, notamment en prod Cloud Run (Groq). Best-effort : n'interrompt jamais.
    """
    settings = get_settings()
    try:
        if settings.llm_provider == "llama":
            from jenny.llm.providers import get_default_llm_provider

            provider = get_default_llm_provider()
            if provider is not None:
                await provider.generate("ping", max_tokens=1)
        from jenny.rag.embeddings import get_default_embedder

        await get_default_embedder().embed_text("ping")
        logger.info("jenny.llm_warmup.done", model=settings.llm_model)
    except Exception as exc:
        logger.warning("jenny.llm_warmup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestion du cycle de vie de l'application.

    - Startup : logging, connexions DB/Redis.
    - Shutdown : fermeture propre des ressources.
    """
    # ── Startup ──
    setup_logging()
    settings = get_settings()
    logger.info(
        "jenny.startup",
        env=settings.env,
        debug=settings.debug,
    )
    if settings.auto_seed:
        try:
            from jenny.scripts.seed_demo import seed_demo

            await seed_demo(force=False)
        except Exception as exc:
            # L'auto-seed ne doit jamais bloquer le démarrage de l'API.
            logger.warning("jenny.auto_seed_failed", error=str(exc))
    # Préchauffage des modèles en tâche de fond (ne bloque pas le démarrage).
    # Référence gardée sur app.state pour éviter un GC prématuré de la tâche.
    app.state.warmup_task = asyncio.create_task(_warmup_models())
    yield
    await close_arq_pool()
    await close_rate_limit_redis()
    logger.info("jenny.shutdown")


def create_app() -> FastAPI:
    """Factory de l'application FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="AI-powered customer message management platform",
        version="0.2.0",
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
        lifespan=lifespan,
    )

    # CORS configurable (JENNY_CORS_ORIGINS) : "*" en dev. En prod, on renseigne
    # l'origine du frontend (ex. https://app.salon.fr) → on peut alors activer les
    # credentials. Avec "*", credentials DOIT rester False (les navigateurs bloquent).
    _cors_raw = (get_settings().cors_origins or "*").strip()
    _cors_origins = (
        ["*"] if _cors_raw == "*" else [o.strip() for o in _cors_raw.split(",") if o.strip()]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_cors_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(AuthContextMiddleware)
    # Ajouté en dernier = couche la plus externe : le rate limiting s'applique
    # avant l'auth, pour rejeter les rafales sur webhooks/ingest au plus tôt.
    app.add_middleware(RateLimitMiddleware)

    # ── Routes ──
    app.include_router(health.router, tags=["health"])
    app.include_router(metrics.router)
    app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
    app.include_router(business.router, prefix="/api/v1", tags=["business"])
    app.include_router(messages.router, prefix="/api/v1", tags=["messages"])
    app.include_router(ingest.router, prefix="/api/v1", tags=["ingestion"])
    app.include_router(conversation.router, prefix="/api/v1", tags=["conversation"])
    app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
    app.include_router(customers.router, prefix="/api/v1", tags=["customers"])
    app.include_router(customer_privacy.router, prefix="/api/v1", tags=["rgpd"])
    app.include_router(canned_responses.router, prefix="/api/v1", tags=["canned"])
    app.include_router(channels.router, prefix="/api/v1", tags=["channels"])
    app.include_router(realtime.router, prefix="/api/v1", tags=["realtime"])
    app.include_router(insights.router, prefix="/api/v1", tags=["insights"])
    app.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])
    app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
    app.include_router(knowledge_gaps.router, prefix="/api/v1", tags=["knowledge-gaps"])
    app.include_router(copilot.router, prefix="/api/v1", tags=["copilot"])
    app.include_router(owner_chat.router, prefix="/api/v1", tags=["owner-assistant"])
    app.include_router(jenny_metrics.router, prefix="/api/v1", tags=["jenny-metrics"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(nanogpt.router, prefix="/api/v1", tags=["nanogpt"])
    app.include_router(llm_settings.router, prefix="/api/v1", tags=["llm"])
    app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
    app.include_router(audit.router, prefix="/api/v1", tags=["audit"])
    app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])
    app.include_router(appointments.router, prefix="/api/v1", tags=["appointments"])
    app.include_router(prestations.router, prefix="/api/v1", tags=["prestations"])
    app.include_router(pending_questions.router, prefix="/api/v1", tags=["pending-questions"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
    app.include_router(search.router, prefix="/api/v1", tags=["search"])
    app.include_router(public_booking.router, prefix="/api/v1", tags=["public-booking"])
    app.include_router(payment_webhooks.router, prefix="/api/v1", tags=["payments"])
    app.include_router(salon_stats.router, prefix="/api/v1", tags=["salon-stats"])
    app.include_router(salon_extras.router, prefix="/api/v1", tags=["salon-extras"])

    instrument_fastapi_if_configured(app)

    return app


# Instance utilisée par uvicorn
app = create_app()
