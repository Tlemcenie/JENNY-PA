"""Charge : 30 chats simultanés sur le pool."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from jenny.db import session as db_session
from jenny.db.session import (
    MAX_CONNECTIONS,
    MAX_OVERFLOW,
    POOL_SIZE,
    build_engines,
    engine_options,
    session_factory,
)

if TYPE_CHECKING:
    from pathlib import Path

PG = "postgresql+asyncpg://u:p@db.example:5432/jenny"
LIVE_PG = os.environ.get("JENNY_TEST_POSTGRES_URL", "")
N_CHATS = 30
LLM_S = 0.2


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JENNY_SQL_ECHO",
        "JENNY_DB_POOLER",
        "JENNY_DB_POOL_SIZE",
        "JENNY_DB_MAX_OVERFLOW",
    ):
        monkeypatch.delenv(name, raising=False)


async def _fake_chat(request_factory, nested_factory) -> None:  # type: ignore[no-untyped-def]
    """Même schéma que _run_engine_chat."""
    async with request_factory() as db:
        # garde + persona + contexte
        await db.execute(text("SELECT 1"))
        # RAG : session à part
        async with nested_factory() as s:
            await s.execute(text("SELECT 1"))
        # appel LLM, connexion gardée
        await asyncio.sleep(LLM_S)
        # handler RDV : session à part
        async with nested_factory() as s:
            await s.execute(text("SELECT 1"))
        # persistance
        await db.execute(text("SELECT 1"))
        await db.commit()


async def _burst(request_factory, nested_factory, n: int = N_CHATS) -> tuple[list, float]:  # type: ignore[no-untyped-def]
    """Lance n chats d'un coup."""
    start = time.monotonic()
    out = await asyncio.gather(
        *(_fake_chat(request_factory, nested_factory) for _ in range(n)),
        return_exceptions=True,
    )
    errors = [e for e in out if isinstance(e, BaseException)]
    return errors, time.monotonic() - start


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}"


def _pool_opts(**over) -> dict:  # type: ignore[no-untyped-def]
    """Options prod (Postgres) pour sqlite."""
    opts = engine_options(PG)
    opts.update(over)
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    opts["poolclass"] = AsyncAdaptedQueuePool
    return opts


def test_defaults_fit_cloud_sql() -> None:
    """4+4 par pool, budget borné."""
    opts = engine_options(PG)
    assert opts["pool_size"] == POOL_SIZE and opts["max_overflow"] == MAX_OVERFLOW
    assert opts["pool_timeout"] == 10
    per_pool = opts["pool_size"] + opts["max_overflow"]
    assert 2 * per_pool == MAX_CONNECTIONS
    # db-g1-small : 47 utiles, 2 workers + arq
    assert 2 * (2 * per_pool) + per_pool <= 47
    # un pool tient 30 chats ?
    assert per_pool < N_CHATS


def test_postgres_gets_two_pools() -> None:
    """Routes et handlers : pools séparés."""
    main, req = build_engines(PG)
    try:
        assert main is not req and main.pool is not req.pool
        assert req.pool.size() == POOL_SIZE and main.pool.size() == POOL_SIZE
    finally:
        asyncio.run(main.dispose())
        asyncio.run(req.dispose())


def test_sqlite_and_pooler_share_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un seul moteur sans QueuePool."""
    main, req = build_engines("sqlite+aiosqlite://")
    assert main is req
    asyncio.run(main.dispose())
    monkeypatch.setenv("JENNY_DB_POOLER", "transaction")
    main, req = build_engines(PG)
    assert main is req
    asyncio.run(main.dispose())


def test_app_wiring() -> None:
    """get_db passe par le pool des routes."""
    assert db_session.request_session_factory.kw["bind"] is db_session.request_engine
    assert db_session.async_session_factory.kw["bind"] is db_session.engine
    # tests sqlite : un seul moteur
    assert db_session.request_engine is db_session.engine


async def test_single_pool_deadlocks(tmp_path: Path) -> None:
    """Ancien schéma : un pool partagé bloque."""
    opts = _pool_opts(pool_timeout=0.5)
    shared = build_engines(_sqlite_url(tmp_path), {**opts, "pool_size": 10, "max_overflow": 10})[0]
    try:
        factory = session_factory(shared)
        errors, _ = await _burst(factory, factory)
    finally:
        await shared.dispose()
    assert errors, "30 chats sur 20 connexions partagées devraient bloquer"
    assert all(isinstance(e, PoolTimeout) for e in errors), errors


async def test_split_pools_no_timeout(tmp_path: Path) -> None:
    """Pools séparés : 30 chats, zéro timeout."""
    main, req = build_engines(_sqlite_url(tmp_path), _pool_opts())
    assert main is not req
    try:
        errors, elapsed = await _burst(session_factory(req), session_factory(main))
        # rafale plus grosse : ça attend, sans casser
        errors_big, _ = await _burst(session_factory(req), session_factory(main), n=60)
    finally:
        await main.dispose()
        await req.dispose()
    print(f"\n[pool] {N_CHATS} chats en {elapsed:.2f} s")
    assert errors == [] and errors_big == []
    # 2 vagues de 0.2 s, loin des 10 s
    assert elapsed < 5


@pytest.mark.services
@pytest.mark.skipif(not LIVE_PG, reason="JENNY_TEST_POSTGRES_URL absent")
async def test_live_postgres_no_timeout() -> None:
    """Vrai Postgres, lecture seule."""
    main, req = build_engines(LIVE_PG)
    assert main is not req
    try:
        errors, elapsed = await _burst(session_factory(req), session_factory(main))
        print(f"\n[pool] postgres : {N_CHATS} chats en {elapsed:.2f} s")
    finally:
        await main.dispose()
        await req.dispose()
    assert errors == []
    assert elapsed < 5
