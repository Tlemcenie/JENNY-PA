"""Client ARQ partagé pour enqueuer des jobs depuis l'API FastAPI."""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.core.metrics import ARQ_JOBS

logger = get_logger(__name__)

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Retourne le pool ARQ (singleton)."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        logger.info("arq.pool.created")
    return _pool


async def close_arq_pool() -> None:
    """Ferme le pool ARQ."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("arq.pool.closed")


async def enqueue_normalize_message(message_id: str) -> None:
    """Enfile la normalisation d'un message après ingestion.

    Sans Redis configuré (mode démo cloud), il n'y a ni file ni worker : on
    saute proprement au lieu de logger une erreur par webhook entrant.
    """
    if not get_settings().redis_url:
        logger.debug("arq.enqueue.skipped_no_redis", message_id=message_id)
        return
    pool = await get_arq_pool()
    await pool.enqueue_job("normalize_message", message_id)
    ARQ_JOBS.labels(job_name="normalize_message").inc()
    logger.info("arq.job.enqueued", job="normalize_message", message_id=message_id)
