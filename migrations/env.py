"""Configuration Alembic pour les migrations.

Supporte le mode async avec SQLAlchemy 2.0.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from jenny.core.config import get_settings
from jenny.db.base import Base

# Importer TOUS les modèles pour que l'autogenerate fonctionne
import jenny.domain.models  # noqa: F401

config = context.config
settings = get_settings()

# Surcharger la DB URL depuis les settings
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables/index créés en SQL brut, donc SANS modèle ORM. Sans ce filtre,
# un `alembic revision --autogenerate` les voit comme « en trop » et génère
# un DROP → ça effacerait toute la base de connaissances RAG.
_TABLES_HORS_ORM = {"document_embeddings"}
_INDEX_HORS_ORM = {"ix_messages_content_fts"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    """Ignore ce qui est géré à la main dans les migrations."""
    if type_ == "table" and name in _TABLES_HORS_ORM:
        return False
    if type_ == "index" and name in _INDEX_HORS_ORM:
        return False
    # index posés en SQL brut sur une table hors ORM
    return not (type_ == "index" and getattr(obj, "table", None) is not None
                and obj.table.name in _TABLES_HORS_ORM)


def run_migrations_offline() -> None:
    """Migrations en mode offline (génère du SQL sans connexion)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Exécute les migrations sur une connexion donnée."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Migrations en mode async."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Migrations en mode online (connexion à la DB)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
