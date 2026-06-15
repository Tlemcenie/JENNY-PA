"""Repository pour les profils clients.

Étend le BaseRepository avec des requêtes spécifiques
à la résolution et déduplication des clients.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.customer import Customer


class CustomerRepository(BaseRepository[Customer]):
    """Opérations de persistance pour les clients."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Customer, session)

    async def find_by_email(self, business_id: UUID, email: str) -> Customer | None:
        """Trouve un client par email dans un business."""
        stmt = select(Customer).where(
            Customer.business_id == business_id,
            Customer.email == email,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_phone(self, business_id: UUID, phone: str) -> Customer | None:
        """Trouve un client par téléphone dans un business."""
        stmt = select(Customer).where(
            Customer.business_id == business_id,
            Customer.phone == phone,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_handle(self, business_id: UUID, handle: str) -> Customer | None:
        """Trouve un client par handle Instagram dans un business."""
        stmt = select(Customer).where(
            Customer.business_id == business_id,
            Customer.instagram_handle == handle,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def resolve_customer(
        self,
        business_id: UUID,
        email: str | None = None,
        phone: str | None = None,
        handle: str | None = None,
    ) -> Customer | None:
        """Résout un client par priorité : email > phone > handle.

        Tente de trouver un client existant en utilisant les
        identifiants disponibles par ordre de fiabilité.
        """
        if email:
            customer = await self.find_by_email(business_id, email)
            if customer:
                return customer

        if phone:
            customer = await self.find_by_phone(business_id, phone)
            if customer:
                return customer

        if handle:
            customer = await self.find_by_handle(business_id, handle)
            if customer:
                return customer

        return None
