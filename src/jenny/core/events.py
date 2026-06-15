"""Bus d'événements temps réel (in-process) pour le flux SSE du dashboard.

Toutes les écritures visibles dans le dashboard (message entrant, réponse de
Jenny ou d'un agent, changement de statut) se produisent dans le processus API.
Un simple bus mémoire à base d'``asyncio.Queue`` suffit donc à pousser ces
événements vers les clients SSE connectés, sans dépendance externe.

Architecture volontairement simple (mono-processus) : la montée en charge
multi-process (Redis pub/sub) est un sujet « pour après ». Les producteurs
publient via :func:`publish_conversation_event` APRÈS le commit DB ; chaque
client SSE consomme sa propre file via :meth:`EventBus.register`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

logger = get_logger(__name__)

# Taille max d'une file par abonné : au-delà, on jette les événements les plus
# anciens (un client lent ne doit jamais bloquer les producteurs). Ce n'est pas
# grave : le frontend recharge la liste complète à chaque notification.
_MAX_QUEUE = 200


class EventBus:
    """Fan-out mémoire : un événement publié est déposé dans chaque file abonnée."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    def register(self) -> asyncio.Queue[dict]:
        """Crée et enregistre une file pour un nouvel abonné (un client SSE)."""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[dict]) -> None:
        """Désenregistre la file d'un abonné qui se déconnecte."""
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict) -> None:
        """Dépose l'événement dans toutes les files abonnées (non bloquant).

        Si une file est pleine (client lent), on retire son plus ancien
        événement pour faire de la place : la fraîcheur prime sur l'exhaustivité.
        """
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # jette le plus ancien
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


# Singleton partagé par tout le processus API.
event_bus = EventBus()


def publish_conversation_event(
    business_id: UUID | str | None,
    *,
    conversation_id: UUID | str | None = None,
    kind: str = "update",
    channel: str | None = None,
) -> None:
    """Publie un événement « la conversation a changé » vers les clients SSE.

    À appeler APRÈS le commit DB pour qu'un rafraîchissement déclenché côté
    client voie bien la donnée. ``kind`` ∈ {inbound, outbound, status, update}.
    """
    if business_id is None:
        return
    event_bus.publish(
        {
            "event": "conversation.update",
            "business_id": str(business_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "kind": kind,
            "channel": channel,
        }
    )


def publish_notification_event(
    business_id: UUID | str | None,
    *,
    recipient: str | None = None,
    kind: str = "system",
    title: str = "",
    conversation_id: UUID | str | None = None,
    notification_id: UUID | str | None = None,
) -> None:
    """Pousse un événement « nouvelle notification » vers les clients SSE.

    Le frontend (cloche) incrémente alors son badge et recharge la liste. Le
    champ ``recipient`` permet au client de filtrer ce qui le concerne ; None =
    visible par toute l'équipe.
    """
    if business_id is None:
        return
    event_bus.publish(
        {
            "event": "notification.new",
            "business_id": str(business_id),
            "recipient": recipient,
            "kind": kind,
            "title": title,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "notification_id": str(notification_id) if notification_id else None,
        }
    )
