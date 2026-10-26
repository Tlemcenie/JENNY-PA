"""Comptes canaux → business.

Unique entre salons seulement pour les canaux routés par l'id (webhooks).
Un login SMTP (« resend », « apikey ») n'est pas unique : id propre au salon.

Limite : premier relié gagne, sans preuve de propriété (pas d'appel Meta).
Le 2e salon a un 409 clair, sa revendication est journalisée, transfert manuel.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.channel_account import ChannelAccount

# canaux routés par id externe
ROUTED_CHANNELS: frozenset[str] = frozenset(
    {"whatsapp", "instagram", "messenger", "twitter", "snapchat"}
)

_CONFLICT = "Ce compte est déjà relié à un autre salon."


def stored_external_id(business_id: UUID, channel: str, external_account_id: str) -> str:
    """Id en base : brut si routé."""
    if channel in ROUTED_CHANNELS:
        return external_account_id
    # propre au salon
    return f"{business_id}:{external_account_id}"[:255]


class ChannelAccountConflictError(HTTPException):
    """Compte déjà pris (409)."""

    def __init__(
        self,
        detail: str = _CONFLICT,
        *,
        owner_business_id: UUID | None = None,
        account_id: UUID | None = None,
    ) -> None:
        super().__init__(status_code=409, detail=detail)
        self.owner_business_id = owner_business_id
        self.account_id = account_id


class ChannelAccountRepository(BaseRepository[ChannelAccount]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ChannelAccount, session)

    async def get_owner_account(
        self, channel: str, external_account_id: str
    ) -> ChannelAccount | None:
        """Compte qui détient cet id."""
        if not external_account_id:
            return None
        stmt = (
            select(ChannelAccount)
            .where(
                ChannelAccount.channel == channel,
                ChannelAccount.external_account_id == external_account_id,
            )
            # premier lié gagne
            .order_by(ChannelAccount.created_at.asc())
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def get_business_for_channel(
        self,
        channel: str,
        external_account_id: str,
    ) -> UUID | None:
        """Salon du compte externe (unique)."""
        if not external_account_id:
            return None
        stmt = (
            select(ChannelAccount.business_id)
            .where(
                ChannelAccount.channel == channel,
                ChannelAccount.external_account_id == external_account_id,
            )
            # premier lié gagne
            .order_by(ChannelAccount.created_at.asc())
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

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
        stored_id = stored_external_id(business_id, channel, external_account_id)
        if channel in ROUTED_CHANNELS:
            owner = await self.get_owner_account(channel, stored_id)
            if owner is not None and owner.business_id != business_id:
                # pas de vol de routage
                raise ChannelAccountConflictError(
                    owner_business_id=owner.business_id, account_id=owner.id
                )
        acct = await self.get_account(business_id, channel)
        if acct is None:
            acct = ChannelAccount(
                business_id=business_id,
                channel=channel,
                external_account_id=stored_id,
                display_name=display_name,
                credentials_=credentials,
            )
            self.session.add(acct)
        else:
            acct.external_account_id = stored_id
            acct.display_name = display_name
            acct.credentials_ = credentials
            acct.last_error = None
        try:
            await self.session.flush()
        except IntegrityError:
            # course : pris entre-temps
            await self.session.rollback()
            raise ChannelAccountConflictError() from None
        return acct

    async def delete_for_business(self, business_id: UUID, channel: str) -> int:
        """Supprime le(s) compte(s) d'un canal pour un business. Renvoie le nb supprimé."""
        stmt = sa_delete(ChannelAccount).where(
            ChannelAccount.business_id == business_id,
            ChannelAccount.channel == channel,
        )
        r = await self.session.execute(stmt)
        return int(r.rowcount or 0)
