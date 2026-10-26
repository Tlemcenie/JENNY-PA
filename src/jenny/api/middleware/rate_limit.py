"""Middleware de limitation de débit (#18).

Couvre les points d'entrée exposés : webhooks, ingestion, réservation publique, l'auth (bcrypt
coûteux, cible du brute-force) et le chat (coût LLM, ouvert au public). Limite
par IP cliente (IPv6 groupée par /64), fenêtre glissante (voir ``core.rate_limit``).
Le chat est aussi plafonné par salon via :func:`enforce_business_chat_limit`. Au dépassement :
HTTP 429 + en-tête ``Retry-After``. Désactivé en ``env=test``.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from jenny.core import rate_limit as core_rl
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.core.rate_limit import check_rate_limit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from starlette.requests import Request
    from starlette.responses import Response

    from jenny.core.config import Settings

logger = get_logger(__name__)

# Préfixes soumis à limitation : points d'entrée externes.
LIMITED_PREFIXES: tuple[str, ...] = (
    "/api/v1/webhooks",
    "/api/v1/ingest",
    # réservation publique, sans compte
    "/api/v1/public",
    # webhooks de paiement
    "/api/v1/payments",
)
AUTH_PREFIX = "/api/v1/auth"
LOGIN_PATH = "/api/v1/auth/login"
CHAT_PREFIX = "/api/v1/conversation"

_TOO_MANY = "Trop de requêtes, réessayez plus tard."


def _client_ip(request: Request) -> str:
    """IP réelle du client, sans faire confiance au XFF forgé."""
    hops = max(0, get_settings().rate_limit_proxy_hops)
    fwd = request.headers.get("x-forwarded-for")
    if fwd and hops:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            # ajoutée par notre proxy
            return parts[-hops] if len(parts) >= hops else parts[0]
    real = request.headers.get("x-real-ip")
    if real and hops:
        return real.strip()
    return request.client.host if request.client else "unknown"


def ip_key(raw: str) -> str:
    """Clé de limite : IPv4, ou IPv6 en /64."""
    raw = (raw or "").strip()
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return raw[:64]
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        # une box = un /64
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def client_key(request: Request) -> str:
    """IP du client, IPv6 groupée."""
    return ip_key(_client_ip(request))


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_limited(path: str) -> bool:
    return any(_matches(path, p) for p in LIMITED_PREFIXES)


def _rule_for(path: str, method: str, settings: Settings) -> tuple[str, int] | None:
    """Seau et plafond pour la route."""
    if _is_limited(path):
        return "ingest", settings.rate_limit_max_requests
    if _matches(path, AUTH_PREFIX):
        # GET /auth/me : léger
        if method in ("GET", "HEAD"):
            return "auth_read", settings.rate_limit_max_requests
        # échecs freinés dans la route
        if path == LOGIN_PATH:
            return "auth_login", settings.rate_limit_login_max_requests
        return "auth", settings.rate_limit_auth_max_requests
    if _matches(path, CHAT_PREFIX):
        return "chat", settings.rate_limit_chat_max_requests
    return None


def limiter_active(settings: Settings | None = None) -> bool:
    """Limiteur actif ?"""
    settings = settings or get_settings()
    return settings.rate_limit_enabled and settings.env != "test"


def _cors_headers(request: Request) -> dict[str, str]:
    """CORS du 429, lisible du front."""
    origin = request.headers.get("origin")
    if not origin:
        return {}
    raw = (get_settings().cors_origins or "*").strip()
    if raw == "*":
        return {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Retry-After"}
    if origin not in [o.strip() for o in raw.split(",") if o.strip()]:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Expose-Headers": "Retry-After",
        "Vary": "Origin",
    }


def _too_many(retry_after: int, request: Request | None = None) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)}
    if request is not None:
        headers.update(_cors_headers(request))
    return JSONResponse({"detail": _TOO_MANY}, status_code=429, headers=headers)


async def enforce_business_chat_limit(business_id: UUID | str) -> None:
    """Plafond de chat par salon, 429 sinon."""
    settings = get_settings()
    if not limiter_active(settings):
        return
    allowed, retry_after = await check_rate_limit(
        str(business_id),
        limit=settings.rate_limit_chat_business_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
        bucket="chat_business",
    )
    if not allowed:
        logger.warning("rate_limit.business_blocked", business_id=str(business_id))
        raise HTTPException(429, _TOO_MANY, headers={"Retry-After": str(retry_after)})


# ── compteur d'échecs ──
# On réserve l'essai AVANT le travail coûteux (bcrypt) : contrôle et comptage
# atomiques, donc une rafale parallèle ne dépasse pas le plafond. Le jeton est
# rendu si l'essai n'était pas un échec.

_FAIL = "fail_"
# pas de plafond
_NO_CAP = 10**9


def _fail_bucket(bucket: str) -> str:
    return f"{_FAIL}{bucket}"


def reset_failures() -> None:
    """Vide les échecs (tests)."""
    core_rl.drop_local(f"ratelimit:{_FAIL}")


async def reserve_failure(bucket: str, key: str, limit: int, window: int) -> str | None:
    """Réserve un essai, None si plafond."""
    ok, _retry, token = await core_rl.take_slot(
        key, limit=limit, window_seconds=window, bucket=_fail_bucket(bucket)
    )
    return token if ok else None


async def release_failure(bucket: str, key: str, token: str | None) -> None:
    """Rend un essai réservé."""
    await core_rl.release_slot(key, token, bucket=_fail_bucket(bucket))


async def recent_failures(bucket: str, key: str, window: int) -> int:
    """Échecs récents, sans compter."""
    return await core_rl.count_slots(key, window_seconds=window, bucket=_fail_bucket(bucket))


async def add_failure(bucket: str, key: str, window: int) -> None:
    """Compte un échec."""
    await core_rl.take_slot(key, limit=_NO_CAP, window_seconds=window, bucket=_fail_bucket(bucket))


async def clear_failures(bucket: str, key: str) -> None:
    """Remise à zéro (succès)."""
    await core_rl.clear_slots(key, bucket=_fail_bucket(bucket))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applique un quota par IP aux routes exposées."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        # Désactivé en test : le client Redis async global se lie à la boucle
        # asyncio courante, incompatible avec les boucles par-test de pytest.
        if not limiter_active(settings) or request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        rule = _rule_for(path, request.method, settings)
        if rule is None:
            return await call_next(request)

        bucket, limit = rule
        # IPv6 : un /64 = un client
        ip = client_key(request)
        allowed, retry_after = await check_rate_limit(
            ip,
            limit=limit,
            window_seconds=settings.rate_limit_window_seconds,
            bucket=bucket,
        )
        if not allowed:
            logger.warning(
                "rate_limit.blocked", ip=ip, path=path, bucket=bucket, retry_after=retry_after
            )
            return _too_many(retry_after, request)
        return await call_next(request)
