"""Repository pour les événements de message.

Gère la trace d'audit des étapes de traitement
d'un message (ingestion, normalisation, classification...).
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.message_event import MessageEvent


class MessageEventRepository(BaseRepository[MessageEvent]):
    """Opérations de persistance pour les événements."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MessageEvent, session)

    async def log_event(
        self,
        message_id: UUID,
        event_type: str,
        status: str = "success",
        detail: str | None = None,
        payload: dict | None = None,
    ) -> MessageEvent:
        """Logue un événement pour un message.

        Args:
            message_id: ID du message concerné.
            event_type: Type d'événement (ingested, normalized, etc.).
            status: Résultat (success, failure, skipped).
            detail: Détails ou message d'erreur.
            payload: Données additionnelles.
        """
        return await self.create(
            message_id=message_id,
            event_type=event_type,
            status=status,
            detail=detail,
            payload=payload,
            created_at=datetime.now(UTC),
        )

    async def list_by_message(self, message_id: UUID) -> list[MessageEvent]:
        """Liste tous les événements d'un message par ordre chronologique."""
        stmt = (
            select(MessageEvent)
            .where(MessageEvent.message_id == message_id)
            .order_by(MessageEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
