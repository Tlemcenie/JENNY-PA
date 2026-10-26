"""Widget : part bornée du cache moteur."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.api.routes import public_chat
from jenny.engine.state_manager import StateManager

HAS_FORGET = hasattr(StateManager, public_chat.EVICT_METHOD)
_NO_FORGET = "StateManager.forget arrive avec le lot moteur"
# Redis jetable, jamais la prod
_REDIS_URL = os.environ.get("JENNY_TEST_REDIS_URL", "")


def _bind(monkeypatch, manager: StateManager) -> StateManager:
    """Moteur du widget = ce manager."""
    monkeypatch.setattr(public_chat, "get_engine", lambda: SimpleNamespace(state_manager=manager))
    return manager


@pytest.fixture(autouse=True)
def _clean():
    public_chat.reset_limits()
    yield
    public_chat.reset_limits()


def test_evict_name_matches_engine() -> None:
    """Nom convenu avec le moteur."""
    assert public_chat.EVICT_METHOD == "forget"


@pytest.mark.skipif(not HAS_FORGET, reason=_NO_FORGET)
async def test_real_forget_bounds_widget_share(monkeypatch) -> None:
    sm = _bind(monkeypatch, StateManager())
    monkeypatch.setattr(public_chat, "MAX_STATES", 2)
    biz = uuid4()
    ids = [uuid4() for _ in range(3)]
    for cid in ids:
        sm.get_or_create(cid, biz, "widget")
        await public_chat._track_state(cid)
    # le plus vieux sort
    assert sm.get(ids[0]) is None
    assert all(sm.get(c) is not None for c in ids[1:])
    assert list(public_chat._STATES) == ids[1:]


@pytest.mark.skipif(not HAS_FORGET, reason=_NO_FORGET)
async def test_busy_conv_not_evicted(monkeypatch) -> None:
    sm = _bind(monkeypatch, StateManager())
    monkeypatch.setattr(public_chat, "MAX_STATES", 1)
    biz = uuid4()
    old, new = uuid4(), uuid4()
    for cid in (old, new):
        sm.get_or_create(cid, biz, "widget")
    await public_chat._track_state(old)
    public_chat._BUSY.add(old)
    await public_chat._track_state(new)
    # en cours : on garde
    assert sm.get(old) is not None
    assert list(public_chat._STATES) == [new]


@pytest.mark.skipif(HAS_FORGET, reason="moteur fusionné")
async def test_without_forget_engine_ttl(monkeypatch) -> None:
    sm = _bind(monkeypatch, StateManager())
    monkeypatch.setattr(public_chat, "MAX_STATES", 1)
    biz = uuid4()
    ids = [uuid4() for _ in range(3)]
    for cid in ids:
        sm.get_or_create(cid, biz, "widget")
        await public_chat._track_state(cid)
    # TTL du moteur seul
    assert all(sm.get(c) is not None for c in ids)
    assert not public_chat._STATES


@pytest.mark.skipif(not HAS_FORGET, reason=_NO_FORGET)
async def test_forget_keeps_redis_copy(monkeypatch) -> None:
    if not _REDIS_URL:
        pytest.skip("JENNY_TEST_REDIS_URL absent")
    sm = StateManager(_REDIS_URL)
    if sm.backend != "redis":
        pytest.skip("Redis injoignable")
    _bind(monkeypatch, sm)
    monkeypatch.setattr(public_chat, "MAX_STATES", 1)
    biz = uuid4()
    old, new = uuid4(), uuid4()
    try:
        for cid in (old, new):
            sm.save(sm.get_or_create(cid, biz, "widget"))
            await public_chat._track_state(cid)
        # mémoire vidée, Redis garde
        assert str(old) not in sm._states
        back = sm.get(old)
        assert back is not None and back.business_id == biz
    finally:
        sm.delete(old)
        sm.delete(new)
        await sm.aclose()
