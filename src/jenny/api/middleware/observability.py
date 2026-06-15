"""Request ID et corrélation (structlog contextvars)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from jenny.core.logging import get_logger
from jenny.core.metrics import HTTP_REQUESTS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = get_logger(__name__)


def _path_group(path: str) -> str:
    parts = [p for p in path.split("/") if p][:2]
    return "/" + "/".join(parts) if parts else "/"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ajoute X-Request-ID et bind request_id / conversation_id dans structlog."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        conv = request.headers.get("X-Conversation-ID")
        if conv:
            structlog.contextvars.bind_contextvars(conversation_id=conv)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            HTTP_REQUESTS.labels(
                method=request.method,
                path_group=_path_group(request.url.path),
            ).inc()
            structlog.contextvars.clear_contextvars()
