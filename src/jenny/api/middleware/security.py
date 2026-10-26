"""Auth : JWT ou clé API pour routes protégées (toujours exigée en prod)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from jenny.api.auth.jwt_utils import decode_token
from jenny.api.dependencies import principal_from_api_key
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.session import async_session_factory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = get_logger(__name__)

PUBLIC_PREFIXES: tuple[str, ...] = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/api/v1/webhooks",
    "/api/v1/auth",
    "/api/v1/payments",
    "/api/v1/ingest/email/inbound",
    "/api/v1/public",
    # chat public, limité en débit
    "/api/v1/conversation/chat",
)


def _is_public(path: str) -> bool:
    if path in ("/", "/favicon.ico"):
        return True
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES)


def _first_uuid(values: object) -> UUID | None:
    """Premier UUID valide."""
    if not isinstance(values, list):
        return None
    for raw in values:
        try:
            return UUID(str(raw))
        except (ValueError, TypeError):
            continue
    return None


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Si l'auth est exigée, demande Authorization Bearer (JWT) ou X-API-Key (sk_...)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        request.state.user_id = None
        request.state.business_id = None
        request.state.auth_scopes = None
        request.state.api_principal = None

        # Les requêtes CORS preflight (OPTIONS) n'embarquent jamais le header
        # Authorization : le navigateur les envoie avant la vraie requête. Si on
        # les rejette en 401, le preflight échoue et le navigateur bloque l'appel
        # réel. On les laisse passer pour que CORSMiddleware produise la réponse.
        if request.method == "OPTIONS":
            return await call_next(request)

        if not settings.auth_required:
            return await call_next(request)

        path = request.url.path
        if _is_public(path):
            return await call_next(request)

        auth = request.headers.get("Authorization") or ""
        api_key_header = request.headers.get("X-API-Key") or ""

        token: str | None = None
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        elif api_key_header.startswith("sk_"):
            token = api_key_header.strip()

        if not token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        if token.startswith("sk_"):
            async with async_session_factory() as session:
                principal = await principal_from_api_key(session, token)
                if principal is not None:
                    await session.commit()
            if principal is None:
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
            request.state.business_id = principal.business_id
            # pas de 2e bcrypt
            request.state.api_principal = principal
        else:
            try:
                claims = decode_token(token)
                request.state.user_id = UUID(str(claims["sub"]))
                request.state.business_id = _first_uuid(claims.get("business_ids"))
            except Exception:
                return JSONResponse({"detail": "Invalid token"}, status_code=401)

        return await call_next(request)
