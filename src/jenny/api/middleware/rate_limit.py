"""Middleware de limitation de débit (#18).

Couvre les points d'entrée exposés : webhooks, ingestion, réservation publique, l'auth (bcrypt
coûteux, cible du brute-force) et le chat (coût LLM, ouvert au public). Limite
par IP cliente, fenêtre glissante (voir ``core.rate_limit``). Le chat est aussi
plafonné par salon via :func:`enforce_business_chat_limit`. Au dépassement :
HTTP 429 + en-tête ``Retry-After``. Désactivé en ``env=test``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
)
AUTH_PREFIX = "/api/v1/auth"
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
        return "auth", settings.rate_limit_auth_max_requests
    if _matches(path, CHAT_PREFIX):
        return "chat", settings.rate_limit_chat_max_requests
    return None


def limiter_active(settings: Settings | None = None) -> bool:
    """Limiteur actif ?"""
    settings = settings or get_settings()
    return settings.rate_limit_enabled and settings.env != "test"


def _too_many(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"detail": _TOO_MANY},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


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
        ip = _client_ip(request)
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
            return _too_many(retry_after)
        return await call_next(request)
