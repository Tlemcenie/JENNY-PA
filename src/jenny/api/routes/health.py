"""Routes de santé et readiness.

Utilisées par les orchestrateurs (Docker, K8s) pour vérifier
que le service est opérationnel.

Checks réels :
- PostgreSQL : tentative de `SELECT 1` via asyncpg
- Redis : tentative de `PING` via redis-py
- ML Models : vérification de la présence des checkpoints
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


async def _check_database() -> dict:
    """Vérifie la connectivité PostgreSQL."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return {"status": "ok", "type": "postgresql"}
    except Exception as e:
        logger.warning("health.db.error", error=str(e))
        return {"status": "error", "type": "postgresql", "error": str(e)[:100]}


async def _check_redis() -> dict:
    """Vérifie la connectivité Redis."""
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        pong = await r.ping()
        await r.aclose()
        return {"status": "ok" if pong else "error", "type": "redis"}
    except ImportError:
        return {"status": "skip", "type": "redis", "reason": "redis-py not installed"}
    except Exception as e:
        logger.warning("health.redis.error", error=str(e))
        return {"status": "error", "type": "redis", "error": str(e)[:100]}


def _check_ml_models() -> dict:
    """Vérifie la présence des checkpoints ML."""
    intent_path = Path("checkpoints/intent/best_model.pt")
    ner_path = Path("checkpoints/ner/best_model.pt")
    return {
        "status": "ok" if intent_path.exists() and ner_path.exists() else "warning",
        "intent_model": "loaded" if intent_path.exists() else "missing",
        "ner_model": "loaded" if ner_path.exists() else "missing",
    }


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Vérifie que l'API est en vie (liveness probe)."""
    return {"status": "healthy", "service": "jenny-api"}


@router.get("/ready")
async def readiness_check() -> dict[str, object]:
    """Vérifie que toutes les dépendances sont prêtes (readiness probe).

    Effectue des checks réels sur :
    - PostgreSQL (SELECT 1)
    - Redis (PING)
    - Modèles ML (fichiers checkpoint)
    """
    settings = get_settings()

    db_check = await _check_database()
    redis_check = await _check_redis()
    ml_check = _check_ml_models()

    checks = {
        "database": db_check,
        "redis": redis_check,
        "ml_models": ml_check,
    }

    # Le service est "ready" tant que DB et Redis répondent.
    # Les modèles ML sont des "nice-to-have" : leur absence renvoie
    # `warning` mais ne bloque pas la readiness.
    critical_ok = all(
        checks[k].get("status") in ("ok", "skip") for k in ("database", "redis")
    )
    all_ok = critical_ok

    return {
        "status": "ready" if all_ok else "degraded",
        "env": settings.env,
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
    }
