"""Réglages du pool et sonde /ready."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from jenny.api.routes import health
from jenny.db.session import engine, engine_options

PG = "postgresql+asyncpg://u:p@db.example:5432/jenny"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("JENNY_SQL_ECHO", "JENNY_DB_POOLER", "JENNY_DB_POOL_SIZE", "JENNY_DB_MAX_OVERFLOW"):
        monkeypatch.delenv(name, raising=False)


def test_sqlite_ignores_pool_args() -> None:
    assert engine_options("sqlite+aiosqlite:///test.db") == {"echo": False, "hide_parameters": True}


def test_postgres_pool_defaults() -> None:
    opts = engine_options(PG)
    assert opts["echo"] is False  # pas de SQL sur stdout
    assert opts["pool_size"] == 10 and opts["max_overflow"] == 10
    assert opts["pool_recycle"] == 1800 and opts["pool_timeout"] == 10
    assert opts["pool_pre_ping"] is True
    assert "connect_args" not in opts and "poolclass" not in opts
    eng = create_async_engine(PG, **opts)  # aucune connexion ouverte
    try:
        assert eng.pool.size() == 10
        assert eng.pool._max_overflow == 10
        assert eng.pool._timeout == 10 and eng.pool._recycle == 1800
    finally:
        asyncio.run(eng.dispose())


def test_echo_only_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_ENV", "dev")
    assert engine_options(PG)["echo"] is False
    assert engine_options(PG)["hide_parameters"] is True
    monkeypatch.setenv("JENNY_SQL_ECHO", "1")
    assert engine_options(PG)["echo"] is True
    assert engine_options(PG)["hide_parameters"] is False  # debug local
    assert engine_options("sqlite+aiosqlite:///x.db")["echo"] is True


@pytest.mark.asyncio
async def test_errors_hide_parameters() -> None:
    from sqlalchemy import text

    eng = create_async_engine("sqlite+aiosqlite://", **engine_options("sqlite+aiosqlite://"))
    try:
        async with eng.connect() as conn:
            with pytest.raises(Exception) as exc:
                await conn.execute(text("SELECT * FROM nope WHERE x = :v"), {"v": "secret@mail.fr"})
        assert "secret@mail.fr" not in str(exc.value)
    finally:
        await eng.dispose()


def test_pool_size_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_DB_POOL_SIZE", "8")
    monkeypatch.setenv("JENNY_DB_MAX_OVERFLOW", "oops")
    opts = engine_options(PG)
    assert opts["pool_size"] == 8 and opts["max_overflow"] == 10
    monkeypatch.setenv("JENNY_DB_POOL_SIZE", "0")  # 0 = illimité, refusé
    assert engine_options(PG)["pool_size"] == 1


def test_transaction_pooler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_DB_POOLER", "transaction")
    opts = engine_options(PG)
    assert opts["poolclass"] is NullPool
    args = opts["connect_args"]
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    name_func = args["prepared_statement_name_func"]
    assert name_func() != name_func()
    assert "pool_size" not in opts
    eng = create_async_engine(PG, **opts)
    try:
        assert isinstance(eng.pool, NullPool)
    finally:
        asyncio.run(eng.dispose())


def test_app_engine_has_no_echo() -> None:
    assert engine.echo is False


@pytest.mark.asyncio
async def test_ready_reuses_app_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlalchemy.ext.asyncio as sa_async

    def _boom(*a, **kw):
        raise AssertionError("nouvel engine créé")

    monkeypatch.setattr(sa_async, "create_async_engine", _boom)
    out = await health._check_database()
    assert out["status"] == "ok", out
    assert out["type"] == engine.dialect.name


@pytest.mark.asyncio
async def test_ready_db_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow() -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(health, "_ping_db", _slow)
    monkeypatch.setattr(health, "_DB_TIMEOUT_S", 0.05)
    out = await health._check_database()
    assert out["status"] == "error" and out["error"]
