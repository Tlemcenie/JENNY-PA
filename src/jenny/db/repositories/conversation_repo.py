"""Repository pour les conversations.

Gère la résolution, la création et la mise à jour
des conversations multicanales.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.conversation import Conversation


class ConversationRepository(BaseRepository[Conversation]):
    """Opérations de persistance pour les conversations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Conversation, session)

    async def find_by_external_id(
        self,
        business_id: UUID,
        channel: str,
        external_conversation_id: str,
    ) -> Conversation | None:
        """Trouve une conversation par son ID externe + canal."""
        stmt = select(Conversation).where(
            Conversation.business_id == business_id,
            Conversation.channel == channel,
            Conversation.external_conversation_id == external_conversation_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_open_for_customer(
        self,
        business_id: UUID,
        customer_id: UUID,
        channel: str,
    ) -> Conversation | None:
        """Trouve une conversation ouverte pour un client sur un canal."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.business_id == business_id,
                Conversation.customer_id == customer_id,
                Conversation.channel == channel,
                Conversation.status.in_(["open", "pending"]),
            )
            .order_by(Conversation.last_message_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_on_new_message(
        self,
        conversation_id: UUID,
        preview: str,
        timestamp: datetime,
    ) -> None:
        """Met à jour la conversation après réception d'un nouveau message."""
        preview_truncated = preview[:200] if len(preview) > 200 else preview
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                last_message_at=timestamp,
                last_message_preview=preview_truncated,
                message_count=Conversation.message_count + 1,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_by_business(
        self,
        business_id: UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """Liste les conversations d'un business avec filtres."""
        stmt = (
            select(Conversation)
            .where(Conversation.business_id == business_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(Conversation.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
