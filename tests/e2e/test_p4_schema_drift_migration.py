"""jen_drift_m6n7 sur le vrai Postgres : tout en ROLLBACK."""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

PG_URL = os.environ.get("JENNY_TEST_POSTGRES_URL", "")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.services,
    pytest.mark.skipif(not PG_URL, reason="JENNY_TEST_POSTGRES_URL absent"),
]


def _mig():  # type: ignore[no-untyped-def]
    path = ROOT / "migrations" / "versions" / "m6n7o8p9q0r1_schema_drift.py"
    spec = importlib.util.spec_from_file_location("mig_drift_e2e", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nullable(conn, cols: list[tuple[str, str]]) -> set[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """Colonnes encore nullables."""
    rows = conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND is_nullable = 'YES'"
        )
    ).all()
    return {(t, c) for t, c in rows} & set(cols)


def _index_count(conn) -> int:  # type: ignore[no-untyped-def]
    return conn.execute(
        text("SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_webhook_deliveries_dedup_key'")
    ).scalar_one()


def _drift(conn) -> list:  # type: ignore[no-untyped-def]
    """Ops autogenerate, filtre de env.py."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import jenny.domain.models  # noqa: F401
    from jenny.db.base import Base
    from jenny.db.schema_filter import include_name, include_object

    ctx = MigrationContext.configure(
        connection=conn,
        opts={"include_object": include_object, "include_name": include_name, "compare_type": True},
    )
    return compare_metadata(ctx, Base.metadata)


@pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")
async def test_descente_nulls_remontee_rejouable() -> None:
    """Descente, NULL remplis, remontée deux fois."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    mig = _mig()
    cols = [(t, c) for t, by_col in mig.NOT_NULL.items() for c in by_col]
    bid, cid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stamp = datetime(2025, 5, 5, 10, 0, tzinfo=UTC)
    seen: dict[str, object] = {}

    def _scenario(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        ops = MigrationContext.configure(conn)
        # base au head : rien à faire
        assert _nullable(conn, cols) == set() and _index_count(conn) == 0
        with Operations.context(ops):
            mig.downgrade()
        seen["down_nullable"] = _nullable(conn, cols)
        seen["down_index"] = _index_count(conn)
        # lignes avec NULL, comme avant
        conn.execute(
            text("INSERT INTO businesses (id, name, slug, is_active) VALUES (:id, 'P4', :s, NULL)"),
            {"id": bid, "s": f"p4-{bid.hex[:12]}"},
        )
        conn.execute(
            text(
                "INSERT INTO conversations (id, business_id, channel, message_count, is_escalated) "
                "VALUES (:id, :b, 'web', NULL, NULL)"
            ),
            {"id": cid, "b": bid},
        )
        conn.execute(
            text(
                "INSERT INTO prestations (id, business_id, name, created_at, updated_at) "
                "VALUES (:id, :b, 'Coupe', NULL, :u)"
            ),
            {"id": pid, "b": bid, "u": stamp},
        )
        with Operations.context(ops):
            mig.upgrade()
            mig.upgrade()  # rejouable
        seen["biz"] = conn.execute(
            text("SELECT is_active FROM businesses WHERE id = :id"), {"id": bid}
        ).one()
        seen["conv"] = conn.execute(
            text("SELECT message_count, is_escalated FROM conversations WHERE id = :id"),
            {"id": cid},
        ).one()
        seen["presta"] = conn.execute(
            text("SELECT created_at, updated_at FROM prestations WHERE id = :id"), {"id": pid}
        ).one()
        seen["up_nullable"] = _nullable(conn, cols)
        seen["up_index"] = _index_count(conn)
        seen["drift"] = _drift(conn)

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            await conn.rollback()
            trans = await conn.begin()
            try:
                await conn.run_sync(_scenario)
            finally:
                await trans.rollback()
            # rien ne reste
            assert (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar() == version
            left = await conn.execute(
                text("SELECT count(*) FROM businesses WHERE id = :id"), {"id": bid}
            )
            assert left.scalar_one() == 0
            await conn.rollback()
    finally:
        await engine.dispose()

    assert seen["down_nullable"] == set(cols)
    assert seen["down_index"] == 1
    assert tuple(seen["biz"]) == (True,)
    assert tuple(seen["conv"]) == (0, False)
    created, updated = seen["presta"]
    # l'autre date sert de repli
    assert created == updated == stamp
    assert seen["up_nullable"] == set() and seen["up_index"] == 0
    assert seen["drift"] == []
