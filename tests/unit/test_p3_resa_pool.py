"""Passe 3 : budget de connexions par process, deux pools gardés."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import AsyncAdaptedQueuePool

from jenny.db.session import (
    MAX_CONNECTIONS,
    build_engines,
    engine_options,
    pool_budget,
    session_factory,
)

if TYPE_CHECKING:
    from pathlib import Path

PG = "postgresql+asyncpg://u:p@db.example:5432/jenny"
# db-g1-small : 50 - 3 réservées
CLOUD_SQL = 47
BURST = 30
LLM_S = 0.2


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JENNY_DB_POOLER",
        "JENNY_DB_MAX_CONNECTIONS",
        "JENNY_DB_POOL_SIZE",
        "JENNY_DB_MAX_OVERFLOW",
    ):
        monkeypatch.delenv(name, raising=False)


def _per_process(opts: dict) -> int:
    """Deux pools par process."""
    return 2 * (opts["pool_size"] + opts["max_overflow"])


def test_defaults_tiennent_deux_workers() -> None:
    opts = engine_options(PG)
    assert _per_process(opts) == MAX_CONNECTIONS == 16
    # arq : seulement le pool principal
    arq = opts["pool_size"] + opts["max_overflow"]
    # prod démo : 1 worker
    assert _per_process(opts) <= CLOUD_SQL
    # avec Redis : 2 workers + arq
    assert 2 * _per_process(opts) + arq <= CLOUD_SQL - 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", (4, 4)), ("10", (3, 2)), ("4", (1, 1)), ("1", (1, 0)), ("beaucoup", (4, 4))],
)
def test_budget(raw: str, expected: tuple[int, int]) -> None:
    size, overflow = pool_budget(raw)
    assert (size, overflow) == expected
    # jamais plus que demandé
    if raw.isdigit():
        assert 2 * (size + overflow) <= max(2, int(raw))


def test_budget_par_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_DB_MAX_CONNECTIONS", "8")
    opts = engine_options(PG)
    assert (opts["pool_size"], opts["max_overflow"]) == (2, 2)
    assert _per_process(opts) == 8
    # réglage fin par pool : gagne
    monkeypatch.setenv("JENNY_DB_POOL_SIZE", "6")
    assert engine_options(PG)["pool_size"] == 6


def test_deux_pools_mais_budget_borne() -> None:
    main, req = build_engines(PG)
    try:
        assert main is not req
        total = sum(e.pool.size() + e.pool._max_overflow for e in (main, req))
        assert total == MAX_CONNECTIONS
    finally:
        asyncio.run(main.dispose())
        asyncio.run(req.dispose())


# ── pourquoi pas un seul pool ──


async def _fake_webhook(request_factory, nested_factory) -> None:  # type: ignore[no-untyped-def]
    """Route webhook : sa session vit pendant la tâche de fond."""
    async with request_factory() as db:
        # canal -> salon
        await db.execute(text("SELECT 1"))
        # tâche de fond (FastAPI : avant la fin du Depends)
        async with nested_factory() as s:
            await s.execute(text("SELECT 1"))
        await asyncio.sleep(LLM_S)
        async with nested_factory() as s:
            await s.execute(text("SELECT 1"))


async def _burst(request_factory, nested_factory):  # type: ignore[no-untyped-def]
    start = time.monotonic()
    out = await asyncio.gather(
        *(_fake_webhook(request_factory, nested_factory) for _ in range(BURST)),
        return_exceptions=True,
    )
    return [e for e in out if isinstance(e, BaseException)], time.monotonic() - start


def _opts(**over) -> dict:  # type: ignore[no-untyped-def]
    """Même attente des deux côtés."""
    opts = engine_options(PG)
    opts.update(poolclass=AsyncAdaptedQueuePool, pool_timeout=2, **over)
    return opts


async def test_pool_partage_bloque(tmp_path: Path) -> None:
    """Même budget, un seul pool : blocage."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'one.db'}"
    shared = build_engines(url, _opts(pool_size=8, max_overflow=8))[0]
    try:
        factory = session_factory(shared)
        errors, _ = await _burst(factory, factory)
    finally:
        await shared.dispose()
    assert errors and all(isinstance(e, PoolTimeout) for e in errors), errors


async def test_deux_pools_passent(tmp_path: Path) -> None:
    """Budget 16 en deux pools : zéro timeout."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'two.db'}"
    main, req = build_engines(url, _opts())
    try:
        errors, elapsed = await _burst(session_factory(req), session_factory(main))
    finally:
        await main.dispose()
        await req.dispose()
    # ça attend, sans bloquer
    assert errors == []
    assert elapsed < 2
