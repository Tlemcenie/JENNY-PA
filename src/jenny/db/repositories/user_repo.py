"""Utilisateurs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.db.repositories.base import BaseRepository
from jenny.domain.models.user import User


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        stmt = select(User).where(User.google_sub == google_sub).limit(1)
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email).limit(1)
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()
