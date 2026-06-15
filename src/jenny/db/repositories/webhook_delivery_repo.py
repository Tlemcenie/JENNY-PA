"""Déduplication des webhooks."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.webhook_delivery import WebhookDelivery


class WebhookDeliveryRepository(BaseRepository[WebhookDelivery]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(WebhookDelivery, session)

    async def exists_dedup_key(self, dedup_key: str) -> bool:
        stmt = select(WebhookDelivery.id).where(WebhookDelivery.dedup_key == dedup_key).limit(1)
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none() is not None

    async def record(self, dedup_key: str, provider: str) -> WebhookDelivery:
        return await self.create(dedup_key=dedup_key, provider=provider)
