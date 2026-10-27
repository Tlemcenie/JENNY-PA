"""Routes async : moteur pris sans geler la boucle."""

from __future__ import annotations

import ast
import asyncio
import itertools
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import jenny.api.routes.webhooks as wh
from jenny.api.main import create_app
from jenny.engine import factory

ROUTES = Path(__file__).resolve().parents[2] / "src" / "jenny" / "api" / "routes"
FILES = (
    "conversation.py",
    "conversations.py",
    "copilot.py",
    "public_chat.py",
    "webhooks.py",
)
# préchauffage simulé
BUILD_S = 0.8
# trou max toléré
MAX_GAP_S = 0.3


class _States:
    """État moteur vide."""

    async def aget(self, conversation_id):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture
def slow_build(monkeypatch: pytest.MonkeyPatch):
    """Lance un build lent (thread)."""
    monkeypatch.setattr(factory, "_engine_singleton", None)
    started = threading.Event()
    fake = SimpleNamespace(state_manager=_States())
    threads: list[threading.Thread] = []

    def _build() -> SimpleNamespace:
        started.set()
        time.sleep(BUILD_S)
        return fake

    monkeypatch.setattr(factory, "build_engine", _build)

    def start() -> SimpleNamespace:
        warm = threading.Thread(target=factory.get_engine, daemon=True)
        threads.append(warm)
        warm.start()
        assert started.wait(2)
        return fake

    yield start
    for warm in threads:
        warm.join(5)


async def _timed(coro):  # type: ignore[no-untyped-def]
    """Résultat, durée, plus long trou."""
    ticks = [time.monotonic()]
    stop = asyncio.Event()

    async def beat() -> None:
        while not stop.is_set():
            await asyncio.sleep(0.01)
            ticks.append(time.monotonic())

    task = asyncio.create_task(beat())
    start = time.monotonic()
    try:
        out = await coro
    finally:
        elapsed = time.monotonic() - start
        stop.set()
        await task
    gap = max(b - a for a, b in itertools.pairwise(ticks))
    return out, elapsed, gap


@pytest.mark.usefixtures("db_tables")
async def test_status_attend_sans_geler(slow_build) -> None:
    app = create_app()
    conv = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        slow_build()
        r, elapsed, gap = await _timed(c.get(f"/api/v1/conversation/status/{conv}"))
    assert r.status_code == 200
    assert r.json() == {"status": "not_found", "conversation_id": str(conv)}
    # a bien attendu le build
    assert elapsed >= BUILD_S / 2
    # boucle restée libre
    assert gap < MAX_GAP_S, gap


async def test_webhook_attend_sans_geler(slow_build) -> None:
    fake = slow_build()
    engine, elapsed, gap = await _timed(wh._get_engine())
    assert engine is fake
    assert elapsed >= BUILD_S / 2
    assert gap < MAX_GAP_S, gap


def _sync_engine_calls(path: Path) -> list[str]:
    """get_engine() appelé en sync dans un async."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "get_engine":
                bad.append(f"{path.name}:{node.lineno}")
    return bad


def test_aucun_get_engine_sync_dans_les_routes() -> None:
    bad = [hit for name in FILES for hit in _sync_engine_calls(ROUTES / name)]
    assert bad == []
    # seam async des webhooks
    tree = ast.parse((ROUTES / "webhooks.py").read_text(encoding="utf-8"))
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_get_engine"
    ]
    assert calls
    assert all(isinstance(parents[id(n)], ast.Await) for n in calls)
