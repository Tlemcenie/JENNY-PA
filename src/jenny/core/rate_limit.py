"""Limiteur de débit à fenêtre glissante (#18).

Backend principal : Redis (déjà dans la stack, partagé multi-process) via un
``sorted set`` par clé — chaque requête est un membre horodaté. Le contrôle et
le comptage se font d'un seul coup dans un script Lua : une rafale parallèle ne
peut pas passer entre les deux.

Repli : si Redis est indisponible (tests, incident), bascule sur un compteur
en mémoire process — moins précis en multi-worker mais ne bloque jamais le
chemin de requête. Même règle : contrôle et comptage sous un verrou.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid
from collections import OrderedDict, deque

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_redis = None
_redis_unavailable = False
# repli mémoire, borné
LOCAL_MAX_KEYS = 50_000
# clé -> (horodatage, jeton)
_local_hits: OrderedDict[str, deque[tuple[float, str]]] = OrderedDict()
_local_lock = threading.Lock()

# vérifie et compte, atomique
_TAKE_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[4]) then
  local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {0, first[2] or ARGV[2]}
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return {1, ARGV[2]}
"""


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


def _key(bucket: str, identifier: str) -> str:
    return f"ratelimit:{bucket}:{identifier}"


def _token(now: float) -> str:
    # unique même à la µs près
    return f"{now:.6f}:{uuid.uuid4().hex[:12]}"


def _local_queue(key: str) -> deque[tuple[float, str]]:
    """File de la clé, LRU borné."""
    dq = _local_hits.get(key)
    if dq is None:
        dq = deque()
        _local_hits[key] = dq
        # vire les plus vieux
        while len(_local_hits) > LOCAL_MAX_KEYS:
            _local_hits.popitem(last=False)
    else:
        _local_hits.move_to_end(key)
    return dq


def _local_take(key: str, limit: int, window: float, now: float, token: str) -> tuple[bool, int]:
    """Vérifie et compte sous verrou."""
    with _local_lock:
        dq = _local_queue(key)
        cutoff = now - window
        while dq and dq[0][0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            retry = int(dq[0][0] + window - now) + 1 if dq else int(window)
            return False, max(1, retry)
        dq.append((now, token))
        return True, 0


def _local_count(key: str, window: float, now: float) -> int:
    with _local_lock:
        dq = _local_hits.get(key)
        if not dq:
            return 0
        while dq and dq[0][0] <= now - window:
            dq.popleft()
        return len(dq)


def _local_release(key: str, token: str) -> None:
    with _local_lock:
        dq = _local_hits.get(key)
        if not dq:
            return
        for item in dq:
            if item[1] == token:
                dq.remove(item)
                return


def drop_local(prefix: str) -> None:
    """Oublie les clés mémoire (tests)."""
    with _local_lock:
        for k in [k for k in _local_hits if k.startswith(prefix)]:
            del _local_hits[k]


async def take_slot(
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    bucket: str = "default",
) -> tuple[bool, int, str | None]:
    """Prend une place, atomique.

    Renvoie ``(autorisé, retry_after, jeton)`` ; le jeton sert à rendre la
    place avec :func:`release_slot`.
    """
    now = time.time()
    key = _key(bucket, identifier)
    token = _token(now)
    redis = await _get_redis()
    if redis is not None:
        try:
            ok, first = await redis.eval(
                _TAKE_LUA,
                1,
                key,
                now - window_seconds,
                now,
                token,
                limit,
                window_seconds + 1,
            )
            if int(ok) == 1:
                return True, 0, token
            retry = int(float(first) + window_seconds - now) + 1
            return False, max(1, retry), None
        except Exception as exc:  # pragma: no cover - redis instable
            logger.warning("rate_limit.redis_error", error=str(exc))
    ok, retry = _local_take(key, limit, float(window_seconds), now, token)
    return ok, retry, token if ok else None


async def release_slot(identifier: str, token: str | None, *, bucket: str = "default") -> None:
    """Rend une place prise."""
    if not token:
        return
    key = _key(bucket, identifier)
    _local_release(key, token)
    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.zrem(key, token)
        except Exception as exc:  # pragma: no cover - redis instable
            logger.warning("rate_limit.redis_error", error=str(exc))


async def count_slots(identifier: str, *, window_seconds: int, bucket: str = "default") -> int:
    """Places prises dans la fenêtre."""
    now = time.time()
    key = _key(bucket, identifier)
    redis = await _get_redis()
    if redis is not None:
        try:
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, "-inf", now - window_seconds)
            pipe.zcard(key)
            _, count = await pipe.execute()
            return int(count)
        except Exception as exc:  # pragma: no cover - redis instable
            logger.warning("rate_limit.redis_error", error=str(exc))
    return _local_count(key, float(window_seconds), now)


async def clear_slots(identifier: str, *, bucket: str = "default") -> None:
    """Vide la clé."""
    key = _key(bucket, identifier)
    with _local_lock:
        _local_hits.pop(key, None)
    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.delete(key)
        except Exception as exc:  # pragma: no cover - redis instable
            logger.warning("rate_limit.redis_error", error=str(exc))


async def check_rate_limit(
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    bucket: str = "default",
) -> tuple[bool, int]:
    """Autorise ou non une requête pour ``identifier`` dans la fenêtre.

    Renvoie ``(autorisé, retry_after_secondes)``. ``retry_after`` n'a de sens que
    si refusé. Contrôle et comptage atomiques (script Lua ou verrou mémoire).
    """
    allowed, retry, _ = await take_slot(
        identifier, limit=limit, window_seconds=window_seconds, bucket=bucket
    )
    return allowed, retry


async def close_rate_limit_redis() -> None:
    """Ferme le client Redis du limiteur (appelé au shutdown)."""
    global _redis
    if _redis is not None:
        with contextlib.suppress(Exception):
            await _redis.aclose()
        _redis = None
