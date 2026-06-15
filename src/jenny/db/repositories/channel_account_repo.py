"""Comptes canaux → business."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.channel_account import ChannelAccount


class ChannelAccountRepository(BaseRepository[ChannelAccount]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ChannelAccount, session)

    async def get_business_for_channel(
        self,
        channel: str,
        external_account_id: str,
    ) -> UUID | None:
        stmt = (
            select(ChannelAccount.business_id)
            .where(
                ChannelAccount.channel == channel,
                ChannelAccount.external_account_id == external_account_id,
            )
            .limit(1)
        )
        r = await self.session.execute(stmt)
        row = r.scalar_one_or_none()
        return row
