"""Compteurs atomiques : mémoire, Redis, widget."""

from __future__ import annotations

import asyncio
import os
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from jenny.api.middleware import rate_limit as mw
from jenny.api.routes import public_chat
from jenny.core import rate_limit as core_rl
from jenny.core.config import get_settings

_REDIS_URL = os.environ.get("JENNY_TEST_REDIS_URL", "")


@pytest.fixture
def memory(monkeypatch: pytest.MonkeyPatch):
    """Repli mémoire seul."""
    monkeypatch.setattr(core_rl, "_redis", None)
    monkeypatch.setattr(core_rl, "_redis_unavailable", True)
    core_rl._local_hits.clear()
    yield
    core_rl._local_hits.clear()


@pytest.fixture
async def redis_backend(monkeypatch: pytest.MonkeyPatch):
    """Vrai Redis, sinon skip."""
    if not _REDIS_URL:
        pytest.skip("JENNY_TEST_REDIS_URL absent")
    import redis.asyncio as aioredis

    client = aioredis.from_url(_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis injoignable")
    monkeypatch.setattr(core_rl, "_redis", client)
    monkeypatch.setattr(core_rl, "_redis_unavailable", False)
    yield client
    await client.aclose()


# ── mémoire ──


async def test_memory_burst_capped(memory) -> None:
    key = uuid4().hex
    res = await asyncio.gather(
        *[core_rl.take_slot(key, limit=5, window_seconds=60, bucket="t") for _ in range(50)]
    )
    assert sum(ok for ok, _, _ in res) == 5


def test_memory_threads_capped(memory) -> None:
    """Sous verrou, même en threads."""
    import threading

    key = core_rl._key("t", uuid4().hex)
    won: list[bool] = []
    go = threading.Barrier(40)

    def _hit() -> None:
        go.wait()
        ok, _ = core_rl._local_take(key, 7, 60.0, time.time(), uuid4().hex)
        won.append(ok)

    threads = [threading.Thread(target=_hit) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert won.count(True) == 7


async def test_release_gives_slot_back(memory) -> None:
    key = uuid4().hex
    ok, _, tok = await core_rl.take_slot(key, limit=1, window_seconds=60, bucket="t")
    assert ok and tok
    assert (await core_rl.take_slot(key, limit=1, window_seconds=60, bucket="t"))[0] is False
    await core_rl.release_slot(key, tok, bucket="t")
    assert (await core_rl.take_slot(key, limit=1, window_seconds=60, bucket="t"))[0] is True


def test_memory_store_bounded(memory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_rl, "LOCAL_MAX_KEYS", 10)
    for i in range(100):
        core_rl._local_take(f"k{i}", 3, 60.0, time.time(), str(i))
    assert len(core_rl._local_hits) == 10


async def test_failure_reservation(memory) -> None:
    mw.reset_failures()
    toks = await asyncio.gather(*[mw.reserve_failure("x", "a@b.fr", 3, 900) for _ in range(20)])
    held = [t for t in toks if t]
    assert len(held) == 3
    assert await mw.recent_failures("x", "a@b.fr", 900) == 3
    await mw.release_failure("x", "a@b.fr", held[0])
    assert await mw.recent_failures("x", "a@b.fr", 900) == 2
    await mw.clear_failures("x", "a@b.fr")
    assert await mw.recent_failures("x", "a@b.fr", 900) == 0
    mw.reset_failures()


# ── vrai Redis (local) ──


async def test_redis_burst_capped(redis_backend) -> None:
    key = uuid4().hex
    res = await asyncio.gather(
        *[core_rl.take_slot(key, limit=5, window_seconds=60, bucket="p3t") for _ in range(50)]
    )
    won = [tok for ok, _, tok in res if ok]
    assert len(won) == 5
    assert all(retry >= 1 for ok, retry, _ in res if not ok)
    assert await core_rl.count_slots(key, window_seconds=60, bucket="p3t") == 5
    await core_rl.release_slot(key, won[0], bucket="p3t")
    assert await core_rl.count_slots(key, window_seconds=60, bucket="p3t") == 4
    await core_rl.clear_slots(key, bucket="p3t")
    assert await core_rl.count_slots(key, window_seconds=60, bucket="p3t") == 0


async def test_redis_failure_reservation(redis_backend) -> None:
    email = f"{uuid4().hex}@b.fr"
    toks = await asyncio.gather(*[mw.reserve_failure("p3x", email, 5, 900) for _ in range(50)])
    held = [t for t in toks if t]
    assert len(held) == 5
    await mw.release_failure("p3x", email, held[0])
    assert await mw.recent_failures("p3x", email, 900) == 4
    await mw.add_failure("p3x", email, 900)
    assert await mw.recent_failures("p3x", email, 900) == 5
    await mw.clear_failures("p3x", email)
    assert await mw.recent_failures("p3x", email, 900) == 0


async def test_redis_check_rate_limit(redis_backend) -> None:
    key = uuid4().hex
    res = await asyncio.gather(
        *[
            core_rl.check_rate_limit(key, limit=3, window_seconds=60, bucket="p3t")
            for _ in range(30)
        ]
    )
    assert [ok for ok, _ in res].count(True) == 3
    await core_rl.clear_slots(key, bucket="p3t")


# ── IP ──


def _req(xff: str) -> Request:
    return Request(
        {"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": ("10.0.0.1", 1)}
    )


def test_client_key_groups_ipv6() -> None:
    assert mw.client_key(_req("2001:db8:1:2::1")) == mw.client_key(_req("2001:db8:1:2:ffff::9"))
    assert mw.client_key(_req("2001:db8:1:2::1")) == "2001:db8:1:2::/64"
    assert mw.client_key(_req("203.0.113.5")) == "203.0.113.5"
    assert mw.ip_key("::ffff:203.0.113.5") == "203.0.113.5"


def test_net_is_48() -> None:
    assert public_chat._net("2001:db8:1:2::/64") == "2001:db8:1::/48"
    assert public_chat._net("203.0.113.5") is None
    assert public_chat._net("pas-une-ip") is None


async def test_middleware_counts_ipv6_by_64(monkeypatch: pytest.MonkeyPatch, memory) -> None:
    from fastapi import FastAPI

    from jenny.core.config import Settings

    s = Settings(_env_file=None, env="dev", rate_limit_auth_max_requests=2, rate_limit_proxy_hops=1)
    monkeypatch.setattr(mw, "get_settings", lambda: s)
    app = FastAPI()
    app.add_middleware(mw.RateLimitMiddleware)

    @app.post("/api/v1/auth/forgot-password")
    async def forgot() -> dict:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        codes = [
            (
                await c.post(
                    "/api/v1/auth/forgot-password",
                    headers={"X-Forwarded-For": f"2001:db8:9:9::{n + 1}"},
                )
            ).status_code
            for n in range(3)
        ]
    # adresses tournantes, même box
    assert codes == [200, 200, 429]


# ── widget : _admit ──


@pytest.fixture
def widget(monkeypatch: pytest.MonkeyPatch):
    """Quota commun qui rend la main."""
    calls: list[str] = []

    async def slow_limit(business_id) -> None:
        calls.append(str(business_id))
        await asyncio.sleep(0.001)

    monkeypatch.setattr(public_chat, "enforce_business_chat_limit", slow_limit)
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    public_chat.reset_limits()
    yield calls
    public_chat.reset_limits()


async def test_admit_burst_new_convs_capped(widget) -> None:
    bid = uuid4()
    res = await asyncio.gather(
        *[public_chat._admit(bid, "203.0.113.70", f"s:{uuid4().hex}", True) for _ in range(50)]
    )
    passed = [w for w, _ in res if w == 0]
    assert len(passed) == public_chat._NEW_IP.limit


async def test_admit_burst_ip_capped(widget) -> None:
    bid = uuid4()
    res = await asyncio.gather(
        *[public_chat._admit(bid, "203.0.113.71", f"s:{uuid4().hex}", False) for _ in range(50)]
    )
    assert [w for w, _ in res].count(0) == public_chat._IP.limit


async def test_admit_refused_shared_gives_back(monkeypatch: pytest.MonkeyPatch, widget) -> None:
    async def full(business_id) -> None:
        await asyncio.sleep(0)
        raise HTTPException(429, "plein")

    monkeypatch.setattr(public_chat, "enforce_business_chat_limit", full)
    bid = uuid4()
    wait, _ = await public_chat._admit(bid, "203.0.113.72", "s:v", False)
    assert wait == 0
    now = time.monotonic()
    # pris sur la réserve seule
    assert public_chat._SALON.used(str(bid), now) == 0
    assert public_chat._SPARE.used(str(bid), now) == 1
    assert public_chat._IP.used("203.0.113.72", now) == 1


async def test_admit_error_gives_back(monkeypatch: pytest.MonkeyPatch, widget) -> None:
    async def broken(business_id) -> None:
        raise HTTPException(503, "panne")

    monkeypatch.setattr(public_chat, "enforce_business_chat_limit", broken)
    bid = uuid4()
    with pytest.raises(HTTPException):
        await public_chat._admit(bid, "203.0.113.73", "s:v", False)
    now = time.monotonic()
    assert public_chat._SALON.used(str(bid), now) == 0
    assert public_chat._IP.used("203.0.113.73", now) == 0


async def test_one_48_cannot_drain_salon(monkeypatch: pytest.MonkeyPatch, widget) -> None:
    """Rotation de /64 dans un /48."""
    monkeypatch.setattr(public_chat._SALON_NET, "limit", 4)
    monkeypatch.setattr(public_chat._SPARE_NET, "limit", 0)
    bid = uuid4()
    codes = []
    for n in range(8):
        ip = f"2001:db8:7:{n:x}::/64"
        codes.append((await public_chat._admit(bid, ip, f"s:{n}", False))[0])
    assert codes.count(0) == 4
    # autre /48 : passe
    assert (await public_chat._admit(bid, "2001:db8:8:1::/64", "s:z", False))[0] == 0
