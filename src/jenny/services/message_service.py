"""Service applicatif pour la consultation des messages.

Fournit les opérations de lecture et de recherche de messages.
L'ingestion est gérée par ingestion_service.py.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jenny.core.exceptions import NotFoundError
from jenny.core.logging import get_logger
from jenny.db.repositories.message_repo import MessageRepository
from jenny.domain.models.message import Message

logger = get_logger(__name__)


class MessageService:
    """Logique métier pour la consultation des messages."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = MessageRepository(session)

    async def get_message(self, message_id: UUID) -> Message:
        """Récupère un message par son ID."""
        message = await self.repo.get_by_id(message_id)
        if not message:
            raise NotFoundError("Message", str(message_id))
        return message

    async def list_messages(
        self,
        business_id: UUID,
        channel: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        """Liste les messages d'un business avec filtres."""
        return await self.repo.list_by_business(
            business_id=business_id,
            channel=channel,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Liste les messages d'une conversation."""
        return await self.repo.list_by_conversation(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
