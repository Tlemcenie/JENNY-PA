"""Gestion des sessions et du moteur async SQLAlchemy.

Fournit l'engine async et le session maker
utilisés par toute l'application.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from jenny.core.config import get_settings

settings = get_settings()

_TRUE = {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, low: int) -> int:
    """Entier depuis l'env, sinon défaut."""
    try:
        return max(low, int(os.getenv(name, "")))
    except ValueError:
        return default


def _pg_stmt_name() -> str:
    """Nom unique pour pgbouncer."""
    return f"__asyncpg_{uuid4()}__"


def engine_options(url: str) -> dict[str, Any]:
    """Options du moteur selon la base."""
    # SQL en clair seulement sur demande
    opts: dict[str, Any] = {"echo": os.getenv("JENNY_SQL_ECHO", "").strip().lower() in _TRUE}
    if url.startswith("sqlite"):
        return opts  # pool par défaut
    if os.getenv("JENNY_DB_POOLER", "").strip().lower() == "transaction":
        # pgbouncer gère déjà le pool
        opts["poolclass"] = NullPool
        opts["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": _pg_stmt_name,
        }
        return opts
    opts.update(
        pool_size=_env_int("JENNY_DB_POOL_SIZE", 5, 1),
        max_overflow=_env_int("JENNY_DB_MAX_OVERFLOW", 5, 0),
        pool_recycle=1800,
        pool_timeout=10,
        pool_pre_ping=True,
    )
    return opts


engine = create_async_engine(settings.database_url, **engine_options(settings.database_url))

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Génère une session async pour injection de dépendances."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
