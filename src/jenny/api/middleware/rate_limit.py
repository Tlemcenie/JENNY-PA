"""Middleware de limitation de débit sur les endpoints d'entrée (#18).

Protège ``/api/v1/webhooks`` et ``/api/v1/ingest`` (les seules routes publiques
recevant du trafic externe non authentifié) contre les abus / rafales. Limite
par IP cliente, fenêtre glissante (voir ``core.rate_limit``). Au dépassement :
HTTP 429 + en-tête ``Retry-After``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.core.rate_limit import check_rate_limit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = get_logger(__name__)

# Préfixes soumis à limitation : points d'entrée externes.
LIMITED_PREFIXES: tuple[str, ...] = (
    "/api/v1/webhooks",
    "/api/v1/ingest",
)


def _client_ip(request: Request) -> str:
    """IP réelle du client : 1er hop de X-Forwarded-For, sinon socket."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def _is_limited(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in LIMITED_PREFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applique un quota par IP aux routes d'ingestion/webhooks."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        # Désactivé en test : le client Redis async global se lie à la boucle
        # asyncio courante, incompatible avec les boucles par-test de pytest.
        if (
            not settings.rate_limit_enabled
            or settings.env == "test"
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        path = request.url.path
        if not _is_limited(path):
            return await call_next(request)

        ip = _client_ip(request)
        allowed, retry_after = await check_rate_limit(
            ip,
            limit=settings.rate_limit_max_requests,
            window_seconds=settings.rate_limit_window_seconds,
            bucket="ingest",
        )
        if not allowed:
            logger.warning("rate_limit.blocked", ip=ip, path=path, retry_after=retry_after)
            return JSONResponse(
                {"detail": "Trop de requêtes, réessayez plus tard."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
