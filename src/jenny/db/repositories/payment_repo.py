"""Paiements Stripe / PayPal."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.payment_record import PaymentRecord


class PaymentRepository(BaseRepository[PaymentRecord]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PaymentRecord, session)

    async def get_by_external(self, provider: str, external_id: str) -> PaymentRecord | None:
        stmt = (
            select(PaymentRecord)
            .where(
                PaymentRecord.provider == provider,
                PaymentRecord.external_id == external_id,
            )
            .limit(1)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def upsert_status(
        self,
        business_id: UUID,
        provider: str,
        external_id: str,
        status: str,
        amount_minor: int | None = None,
        order_reference: str | None = None,
    ) -> PaymentRecord:
        existing = await self.get_by_external(provider, external_id)
        if existing:
            existing.status = status
            if amount_minor is not None:
                existing.amount_minor = amount_minor
            if order_reference:
                existing.order_reference = order_reference
            await self.session.flush()
            return existing
        return await self.create(
            business_id=business_id,
            provider=provider,
            external_id=external_id,
            status=status,
            amount_minor=amount_minor,
            order_reference=order_reference,
        )
