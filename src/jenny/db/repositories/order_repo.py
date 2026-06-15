"""Commandes."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.order import Order


class OrderRepository(BaseRepository[Order]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Order, session)

    async def get_by_reference(
        self,
        business_id: UUID,
        reference: str,
    ) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.business_id == business_id, Order.reference == reference)
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()
