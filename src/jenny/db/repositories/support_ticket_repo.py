"""Tickets support."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.support_ticket import SupportTicket


class SupportTicketRepository(BaseRepository[SupportTicket]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SupportTicket, session)

    async def create_ticket(
        self,
        business_id: UUID,
        customer_id: UUID | None,
        subject: str,
        reference: str | None = None,
        status: str = "open",
    ) -> SupportTicket:
        return await self.create(
            business_id=business_id,
            customer_id=customer_id,
            subject=subject,
            reference=reference,
            status=status,
            priority="normal",
        )
