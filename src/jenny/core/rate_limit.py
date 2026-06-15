"""Limiteur de débit à fenêtre glissante (#18).

Backend principal : Redis (déjà dans la stack, partagé multi-process) via un
``sorted set`` par clé — chaque requête est un membre horodaté ; on purge les
entrées hors fenêtre puis on compte. Atomique grâce à un pipeline.

Repli : si Redis est indisponible (tests, incident), bascule sur un compteur
en mémoire process — moins précis en multi-worker mais ne bloque jamais le
chemin de requête. Un incident Redis ne doit pas faire tomber les webhooks.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict, deque

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_redis = None
_redis_unavailable = False
# Repli mémoire : clé -> file des horodatages (monotone) des requêtes récentes.
_local_hits: dict[str, deque[float]] = defaultdict(deque)


async def _get_redis():
    """Client redis.asyncio paresseux ; None si indisponible (repli mémoire)."""
    global _redis, _redis_unavailable
    if _redis is not None or _redis_unavailable:
        return _redis
    try:
        import redis.asyncio as aioredis

        # Timeouts courts : si le port est ouvert mais que Redis ne répond pas
        # (incident, conteneur à moitié démarré), la connexion ne doit pas
        # bloquer le chemin de requête — on bascule vite sur le repli mémoire.
        _redis = aioredis.from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.5,
        )
        # ``socket_timeout`` ne couvre pas un port ouvert qui n'envoie jamais de
        # réponse : on borne explicitement le ping pour ne jamais rester pendu.
        await asyncio.wait_for(_redis.ping(), timeout=2.0)
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        _redis_unavailable = True
        with contextlib.suppress(Exception):
            if _redis is not None:
                await _redis.aclose()
        _redis = None
        logger.warning("rate_limit.redis_unavailable", error=str(exc))
    return _redis


def _check_local(key: str, limit: int, window: float, now: float) -> tuple[bool, int]:
    """Fenêtre glissante en mémoire (repli)."""
    dq = _local_hits[key]
    cutoff = now - window
    while dq and dq[0] <= cutoff:
        dq.popleft()
    if len(dq) >= limit:
        retry = int(dq[0] + window - now) + 1
        return False, max(1, retry)
    dq.append(now)
    return True, 0


async def check_rate_limit(
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    bucket: str = "default",
) -> tuple[bool, int]:
    """Autorise ou non une requête pour ``identifier`` dans la fenêtre.

    Renvoie ``(autorisé, retry_after_secondes)``. ``retry_after`` n'a de sens que
    si refusé. La granularité Redis est la milliseconde (membres uniques).
    """
    now = time.time()
    key = f"ratelimit:{bucket}:{identifier}"
    redis = await _get_redis()
    if redis is None:
        return _check_local(key, limit, float(window_seconds), now)

    cutoff = now - window_seconds
    member = f"{now:.6f}"
    try:
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
        if int(count) > limit:
            # Au-delà du quota : on retire notre propre marqueur (il ne doit pas
            # compter ni prolonger l'attente des requêtes légitimes suivantes).
            await redis.zrem(key, member)
            oldest = await redis.zrange(key, 0, 0, withscores=True)
            retry = window_seconds
            if oldest:
                retry = int(oldest[0][1] + window_seconds - now) + 1
            return False, max(1, retry)
        return True, 0
    except Exception as exc:  # pragma: no cover
        logger.warning("rate_limit.redis_error", error=str(exc))
        return _check_local(key, limit, float(window_seconds), now)


async def close_rate_limit_redis() -> None:
    """Ferme le client Redis du limiteur (appelé au shutdown)."""
    global _redis
    if _redis is not None:
        with contextlib.suppress(Exception):
            await _redis.aclose()
        _redis = None
