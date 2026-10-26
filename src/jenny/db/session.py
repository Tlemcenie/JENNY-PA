"""Gestion des sessions et du moteur async SQLAlchemy.

Deux pools sur Postgres : ``request_engine`` pour les routes (``get_db``),
``engine`` pour le reste (handlers, RAG, webhooks, tâches). Un seul pool
partagé peut se bloquer : une session de route vit jusqu'à la fin des
tâches de fond (webhooks WhatsApp/Insta, LLM compris) pendant que ces
tâches ouvrent leurs propres sessions.

Budget : ``JENNY_DB_MAX_CONNECTIONS`` (défaut 16) par process, partagé
entre les deux pools (4 + 4 chacun). Total en base = instances x
workers uvicorn x budget + worker arq (8). Prod démo (1 instance,
1 worker) : 16. Avec Redis (2 workers) : 2 x 16 + 8 = 40, sous les 47
de db-g1-small. Plus d'instances : baisser le budget ou passer par
``JENNY_DB_POOLER=transaction``. Voir docs/db_pool.md.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from jenny.core.config import Settings, get_settings

settings = get_settings()

_TRUE = {"1", "true", "yes", "on"}

# budget par process, 2 pools
MAX_CONNECTIONS = 16
# défauts d'un pool (16 / 2)
POOL_SIZE = 4
MAX_OVERFLOW = 4
POOL_TIMEOUT_S = 10
POOL_RECYCLE_S = 1800


class _PoolSettings(BaseSettings):
    """Réglages du pool (env ou .env)."""

    model_config = SettingsConfigDict(
        env_prefix="JENNY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # texte brut, lu avec tolérance
    sql_echo: str = ""
    db_pooler: str = ""
    db_max_connections: str = ""
    db_pool_size: str = ""
    db_max_overflow: str = ""


def _pool_settings() -> _PoolSettings:
    """Relu à chaque appel, même .env que Settings."""
    return _PoolSettings(_env_file=Settings.model_config.get("env_file"))


def _as_int(raw: str, default: int, low: int) -> int:
    """Entier tolérant, sinon défaut."""
    try:
        return max(low, int(raw))
    except ValueError:
        return default


def pool_budget(raw: str = "") -> tuple[int, int]:
    """(taille, débord) d'un pool."""
    total = _as_int(raw, MAX_CONNECTIONS, 2)
    # moitié par pool
    per_pool = total // 2
    size = (per_pool + 1) // 2
    return size, per_pool - size


def _pg_stmt_name() -> str:
    """Nom unique pour pgbouncer."""
    return f"__asyncpg_{uuid4()}__"


def engine_options(url: str) -> dict[str, Any]:
    """Options du moteur selon la base."""
    conf = _pool_settings()
    # SQL en clair seulement sur demande
    echo = conf.sql_echo.strip().lower() in _TRUE
    # pas de données perso dans les logs
    opts: dict[str, Any] = {"echo": echo, "hide_parameters": not echo}
    if url.startswith("sqlite"):
        return opts  # pool par défaut
    if conf.db_pooler.strip().lower() == "transaction":
        # pgbouncer gère déjà le pool
        opts["poolclass"] = NullPool
        opts["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": _pg_stmt_name,
        }
        return opts
    size, overflow = pool_budget(conf.db_max_connections)
    opts.update(
        # réglage fin par pool
        pool_size=_as_int(conf.db_pool_size, size, 1),
        max_overflow=_as_int(conf.db_max_overflow, overflow, 0),
        pool_recycle=POOL_RECYCLE_S,
        pool_timeout=POOL_TIMEOUT_S,
        pool_pre_ping=True,
    )
    return opts


def build_engines(url: str, opts: dict[str, Any] | None = None) -> tuple[AsyncEngine, AsyncEngine]:
    """Moteur principal + moteur des routes."""
    opts = engine_options(url) if opts is None else opts
    main = create_async_engine(url, **opts)
    if "pool_size" not in opts:
        return main, main  # sqlite ou pgbouncer
    return main, create_async_engine(url, **opts)


def session_factory(bind: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions sur un moteur."""
    return async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)


engine, request_engine = build_engines(settings.database_url)

async_session_factory = session_factory(engine)
# même fabrique si un seul moteur
request_session_factory = (
    async_session_factory if request_engine is engine else session_factory(request_engine)
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Génère une session async pour injection de dépendances."""
    async with request_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
