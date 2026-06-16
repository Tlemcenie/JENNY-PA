"""Comptes canaux → business."""

from uuid import UUID

from sqlalchemy import delete as sa_delete
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

    async def get_account(self, business_id: UUID, channel: str) -> ChannelAccount | None:
        """Le compte de canal d'un business (le plus récent si plusieurs)."""
        stmt = (
            select(ChannelAccount)
            .where(
                ChannelAccount.business_id == business_id,
                ChannelAccount.channel == channel,
            )
            .order_by(ChannelAccount.created_at.desc())
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def list_for_business(self, business_id: UUID) -> list[ChannelAccount]:
        stmt = select(ChannelAccount).where(ChannelAccount.business_id == business_id)
        r = await self.session.execute(stmt)
        return list(r.scalars().all())

    async def list_with_credentials(self, channel: str) -> list[ChannelAccount]:
        """Tous les comptes d'un canal qui portent des identifiants (multi-tenant)."""
        stmt = select(ChannelAccount).where(
            ChannelAccount.channel == channel,
            ChannelAccount.credentials_.isnot(None),
        )
        r = await self.session.execute(stmt)
        return list(r.scalars().all())

    async def upsert(
        self,
        *,
        business_id: UUID,
        channel: str,
        external_account_id: str,
        display_name: str | None,
        credentials: dict | None,
    ) -> ChannelAccount:
        """Crée ou met à jour le compte de canal d'un business (1 par canal)."""
        acct = await self.get_account(business_id, channel)
        if acct is None:
            acct = ChannelAccount(
                business_id=business_id,
                channel=channel,
                external_account_id=external_account_id,
                display_name=display_name,
                credentials_=credentials,
            )
            self.session.add(acct)
        else:
            acct.external_account_id = external_account_id
            acct.display_name = display_name
            acct.credentials_ = credentials
            acct.last_error = None
        await self.session.flush()
        return acct

    async def delete_for_business(self, business_id: UUID, channel: str) -> int:
        """Supprime le(s) compte(s) d'un canal pour un business. Renvoie le nb supprimé."""
        stmt = sa_delete(ChannelAccount).where(
            ChannelAccount.business_id == business_id,
            ChannelAccount.channel == channel,
        )
        r = await self.session.execute(stmt)
        return int(r.rowcount or 0)
