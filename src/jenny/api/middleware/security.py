"""Auth optionnelle : JWT ou clé API pour routes protégées."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from jenny.api.auth.api_key_crypto import verify_api_key
from jenny.api.auth.jwt_utils import decode_token
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.session import async_session_factory
from jenny.domain.models.api_key import ApiKey

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
)


def _is_public(path: str) -> bool:
    if path in ("/", "/favicon.ico"):
        return True
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Si require_auth=True, exige Authorization Bearer (JWT) ou X-API-Key (sk_...)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        request.state.user_id = None
        request.state.business_id = None
        request.state.auth_scopes = None

        # Les requêtes CORS preflight (OPTIONS) n'embarquent jamais le header
        # Authorization : le navigateur les envoie avant la vraie requête. Si on
        # les rejette en 401, le preflight échoue et le navigateur bloque l'appel
        # réel. On les laisse passer pour que CORSMiddleware produise la réponse.
        if request.method == "OPTIONS":
            return await call_next(request)

        if not settings.require_auth:
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
            token = api_key_header

        if not token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        if token.startswith("sk_"):
            prefix = token[:16] if len(token) >= 16 else token
            async with async_session_factory() as session:
                stmt = select(ApiKey).where(ApiKey.key_prefix == prefix)
                r = await session.execute(stmt)
                keys = list(r.scalars().all())
                matched = False
                for ak in keys:
                    if verify_api_key(token, ak.key_hash):
                        request.state.business_id = ak.business_id
                        request.state.auth_scopes = ak.scopes
                        ak.last_used_at = datetime.now(UTC)
                        matched = True
                        break
                if matched:
                    await session.commit()
            if request.state.business_id is None:
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
        else:
            try:
                claims = decode_token(token)
                request.state.user_id = UUID(claims["sub"])
                bids = claims.get("business_ids") or []
                if bids:
                    request.state.business_id = UUID(bids[0])
            except Exception:
                return JSONResponse({"detail": "Invalid token"}, status_code=401)

        return await call_next(request)
