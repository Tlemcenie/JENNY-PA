"""Repository pour les messages.

Gère la persistance, la déduplication et les requêtes
spécifiques aux messages.
"""

import base64
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.message import Message


class MessageRepository(BaseRepository[Message]):
    """Opérations de persistance pour les messages."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Message, session)

    async def exists_by_external_id(
        self,
        business_id: UUID,
        channel: str,
        external_message_id: str,
    ) -> bool:
        """Vérifie si un message existe déjà (déduplication).

        La déduplication se fait sur le triplet :
        (business_id, channel, external_message_id)
        """
        stmt = (
            select(Message.id)
            .where(
                Message.business_id == business_id,
                Message.channel == channel,
                Message.external_message_id == external_message_id,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Liste les messages d'une conversation par ordre chronologique."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.source_created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_business(
        self,
        business_id: UUID,
        channel: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        """Liste les messages d'un business avec filtres optionnels."""
        stmt = (
            select(Message)
            .where(Message.business_id == business_id)
            .order_by(Message.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if channel:
            stmt = stmt.where(Message.channel == channel)
        if status:
            stmt = stmt.where(Message.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_business_cursor(
        self,
        business_id: UUID,
        *,
        limit: int = 20,
        cursor: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> tuple[list[Message], str | None]:
        """Liste paginée par curseur (received_at, id)."""
        stmt = select(Message).where(Message.business_id == business_id)
        if channel:
            stmt = stmt.where(Message.channel == channel)
        if status:
            stmt = stmt.where(Message.status == status)
        if from_date:
            stmt = stmt.where(Message.received_at >= from_date)
        if to_date:
            stmt = stmt.where(Message.received_at <= to_date)

        if cursor:
            try:
                raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
                data = json.loads(raw.decode("utf-8"))
                ra = datetime.fromisoformat(data["r"])
                mid = UUID(data["i"])
                stmt = stmt.where(
                    (Message.received_at < ra)
                    | ((Message.received_at == ra) & (Message.id < mid))
                )
            except (ValueError, KeyError, json.JSONDecodeError, OSError):
                pass

        stmt = stmt.order_by(Message.received_at.desc(), Message.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        next_cursor: str | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            if last.received_at:
                payload = json.dumps(
                    {"r": last.received_at.isoformat(), "i": str(last.id)},
                    separators=(",", ":"),
                )
                next_cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        return rows, next_cursor

    async def get_by_id_for_business(self, message_id: UUID, business_id: UUID) -> Message | None:
        stmt = (
            select(Message)
            .where(Message.id == message_id, Message.business_id == business_id)
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()
