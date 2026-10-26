"""Filtre autogenerate : objets hors ORM."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jenny.db.schema_filter import (
    COLONNES_HORS_ORM,
    CONTRAINTES_HORS_ORM,
    INDEX_HORS_ORM,
    PROTEGES,
    TABLES_HORS_ORM,
    include_name,
    include_object,
)

ROOT = Path(__file__).resolve().parents[2]
LIVE_PG = os.environ.get("JENNY_TEST_POSTGRES_URL", "")
HORS_ORM = TABLES_HORS_ORM | INDEX_HORS_ORM | CONTRAINTES_HORS_ORM | PROTEGES


def _obj(table: str) -> SimpleNamespace:
    return SimpleNamespace(table=SimpleNamespace(name=table))


def _migrations_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "migrations/versions").glob("*.py"))


def test_raw_objects_ignored() -> None:
    assert include_object(None, "document_embeddings", "table", True, None) is False
    assert include_name("document_embeddings", "table", {}) is False
    assert include_object(_obj("document_embeddings"), "ix_x", "index", True, None) is False
    assert include_object(_obj("document_embeddings"), "content_tsv", "column", True, None) is False
    assert include_object(_obj("appointments"), "appointments_no_overlap", "index", True, None) is False
    assert (
        include_object(_obj("appointments"), "appointments_end_after_start", "check_constraint", True, None)
        is False
    )
    assert include_object(_obj("messages"), "ix_messages_business_received", "index", True, None) is False


def test_protected_only_when_missing_from_models() -> None:
    name = "uq_payments_provider_external"
    # en base, absent du modèle : gardé
    assert include_object(_obj("payments"), name, "unique_constraint", True, None) is False
    # déclaré plus tard dans le modèle : comparé
    assert include_object(_obj("payments"), name, "unique_constraint", False, object()) is True


def test_normal_objects_compared() -> None:
    assert include_object(None, "customers", "table", False, None) is True
    assert include_name("customers", "table", {}) is True
    assert include_object(_obj("customers"), "ix_customers_phone", "index", True, None) is True
    assert include_object(_obj("customers"), "phone", "column", False, None) is True


def test_names_exist_in_migrations() -> None:
    """Pas de nom inventé."""
    text = _migrations_text()
    missing = sorted(n for n in HORS_ORM if n not in text)
    missing += sorted(f"{t}.{c}" for t, c in COLONNES_HORS_ORM if c not in text)
    assert missing == []


@pytest.mark.services
@pytest.mark.skipif(not LIVE_PG, reason="JENNY_TEST_POSTGRES_URL absent")
async def test_live_autogenerate_never_drops_raw_objects() -> None:
    """Vrai Postgres migré, lecture seule."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    import jenny.domain.models  # noqa: F401
    from jenny.db.base import Base

    def _diff(conn):  # type: ignore[no-untyped-def]
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_object": include_object,
                "include_name": include_name,
                "compare_type": True,
            },
        )
        return compare_metadata(ctx, Base.metadata)

    eng = create_async_engine(LIVE_PG, poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            diffs = await conn.run_sync(_diff)
    finally:
        await eng.dispose()

    flat = [d for item in diffs for d in (item if isinstance(item, list) else [item])]
    kinds = {d[0] for d in flat}
    # rien de destructif sur les tables
    assert "remove_table" not in kinds and "remove_column" not in kinds, kinds
    touched = {getattr(d[1], "name", None) for d in flat if d[0].startswith("remove_")}
    assert not touched & HORS_ORM, touched & HORS_ORM
