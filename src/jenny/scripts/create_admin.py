"""Crée (ou promeut) un super-administrateur plateforme.

Usage :
    PYTHONPATH=src python -m jenny.scripts.create_admin
    PYTHONPATH=src python -m jenny.scripts.create_admin --email me@x.com --password 'S3cret!'

Idempotent : si le compte existe déjà, il est promu super-admin (et son mot de
passe mis à jour si fourni). Sinon il est créé, email vérifié, super-admin.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from jenny.api.auth.password_utils import hash_password
from jenny.core.logging import get_logger
from jenny.db.session import async_session_factory
from jenny.domain.models.user import User

logger = get_logger(__name__)

DEFAULT_EMAIL = "admin@jenny.ai"
DEFAULT_PASSWORD = "Admin!2026"


async def create_admin(email: str, password: str | None) -> None:
    async with async_session_factory() as session, session.begin():
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                full_name="Administrateur Jenny",
                password_hash=hash_password(password or DEFAULT_PASSWORD),
                email_verified=True,
                is_superuser=True,
            )
            session.add(user)
            action = "créé"
        else:
            user.is_superuser = True
            user.email_verified = True
            if password:
                user.password_hash = hash_password(password)
            action = "promu"
    logger.info("admin.ready", email=email, action=action)
    print(f"✅ Super-admin {action} : {email}")
    if password or user is None:
        print(f"   mot de passe : {password or DEFAULT_PASSWORD}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Créer/promouvoir un super-admin Jenny")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()
    asyncio.run(create_admin(args.email, args.password))


if __name__ == "__main__":
    main()
