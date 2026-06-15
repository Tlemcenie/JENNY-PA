"""Flux temps réel (Server-Sent Events) pour le dashboard.

``GET /realtime/stream`` ouvre une connexion SSE : le serveur pousse un
événement à chaque changement (message entrant, réponse, statut) concernant
le business de l'utilisateur. Le frontend recharge alors la liste, sans avoir
à interroger l'API toutes les N secondes.

Authentification : header ``Authorization: Bearer`` comme partout (le frontend
consomme le flux via ``fetch`` + ReadableStream, pas via ``EventSource`` natif
qui ne sait pas envoyer d'en-tête). Aucun jeton ne transite par l'URL.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from jenny.api.dependencies import CurrentUser  # noqa: TC001 — requis au runtime par FastAPI
from jenny.core.events import event_bus
from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["Realtime"])

# Intervalle des battements de cœur (commentaires SSE) qui maintiennent la
# connexion ouverte à travers proxys et navigateurs.
_HEARTBEAT_SECONDS = 20.0


async def sse_event_stream(
    business_id: str | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    heartbeat: float = _HEARTBEAT_SECONDS,
    max_events: int | None = None,
) -> AsyncIterator[str]:
    """Générateur de trames SSE, filtrées sur ``business_id``.

    Découplé de FastAPI pour être testable directement (le transport ASGI de
    httpx bufferise les réponses et ne sait pas streamer un flux infini).
    ``is_disconnected`` permet d'arrêter proprement quand le client part ;
    ``max_events`` borne le flux (utilisé par les tests).
    """
    queue = event_bus.register()
    logger.info("sse.connected", business_id=business_id, subscribers=event_bus.subscriber_count)
    sent = 0
    try:
        # Premier octet immédiat : ouvre le flux côté client (et confirme l'auth).
        yield ": connected\n\n"
        while True:
            if await is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"  # battement de cœur (commentaire ignoré par le client)
                continue

            # Cloisonnement multi-tenant : on ne pousse que les événements
            # du business de l'utilisateur authentifié.
            if business_id and event.get("business_id") != business_id:
                continue

            yield f"event: {event.get('event', 'message')}\ndata: {json.dumps(event)}\n\n"
            sent += 1
            if max_events is not None and sent >= max_events:
                break
    finally:
        event_bus.unregister(queue)
        logger.info(
            "sse.disconnected", business_id=business_id, subscribers=event_bus.subscriber_count
        )


@router.get("/stream")
async def stream_events(request: Request, principal: CurrentUser) -> StreamingResponse:
    """Ouvre un flux SSE filtré sur le business de l'utilisateur."""
    bid = str(principal.business_id) if principal.business_id else None

    return StreamingResponse(
        sse_event_stream(bid, request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # désactive le buffering nginx
        },
    )
