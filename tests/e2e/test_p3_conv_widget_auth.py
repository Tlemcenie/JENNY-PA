"""Auth : rafales parallèles bornées."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import jenny.domain.models  # noqa: F401
from jenny.api.auth.email_verification import MAX_VERIFY_ATTEMPTS
from jenny.api.auth.password_utils import hash_password
from jenny.api.main import create_app
from jenny.api.middleware import rate_limit as mw
from jenny.core import rate_limit as core_rl
from jenny.core.config import get_settings
from jenny.db.session import async_session_factory
from jenny.domain.models.user import User

pytestmark = pytest.mark.usefixtures("db_tables")

_PWD = "Demo!1234"
_BAD = {"code": "000001", "new_password": "Nouveau!123"}


# Redis jetable, jamais la prod
_REDIS_URL = os.environ.get("JENNY_TEST_REDIS_URL", "")


async def _wipe(client) -> None:
    """Vide les clés du limiteur."""
    keys = [k async for k in client.scan_iter(match="ratelimit:*")]
    if keys:
        await client.delete(*keys)


@pytest.fixture(params=["memoire", "redis"])
async def limiter(request, monkeypatch: pytest.MonkeyPatch):
    """Limiteur actif, mémoire ou vrai Redis."""
    s = get_settings()
    monkeypatch.setattr(s, "env", "dev")
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    client = None
    if request.param == "redis":
        if not _REDIS_URL:
            pytest.skip("JENNY_TEST_REDIS_URL absent")
        import redis.asyncio as aioredis

        client = aioredis.from_url(_REDIS_URL, decode_responses=True)
        await _wipe(client)
    monkeypatch.setattr(core_rl, "_redis", client)
    monkeypatch.setattr(core_rl, "_redis_unavailable", client is None)
    core_rl._local_hits.clear()
    mw.reset_failures()
    yield s
    core_rl._local_hits.clear()
    mw.reset_failures()
    if client is not None:
        await _wipe(client)
        await client.aclose()


@pytest.fixture
async def client(limiter):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _user(**kw) -> str:
    email = f"gerant-{uuid4().hex[:6]}@salon.fr"
    fields = {"email": email, "password_hash": hash_password(_PWD), "email_verified": True}
    fields.update(kw)
    async with async_session_factory() as s, s.begin():
        s.add(User(**fields))
    return email


async def _forgot(c: AsyncClient, email: str) -> str:
    r = await c.post("/api/v1/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    return r.json().get("debug_code", "")


async def _reset(c: AsyncClient, email: str, ip: str, **kw) -> int:
    r = await c.post(
        "/api/v1/auth/reset-password",
        json={"email": email, **_BAD, **kw},
        headers={"X-Forwarded-For": ip},
    )
    return r.status_code


async def test_reset_burst_one_ip_capped(client: AsyncClient) -> None:
    email = await _user()
    await _forgot(client, email)
    codes = await asyncio.gather(*[_reset(client, email, "198.51.100.9") for _ in range(50)])
    # 5 essais par (email, IP)
    assert codes.count(400) <= 5
    assert codes.count(400) + codes.count(429) == 50


async def test_reset_burst_many_ips_capped(client: AsyncClient) -> None:
    email = await _user()
    await _forgot(client, email)
    ips = [f"198.51.{i // 200}.{i % 200 + 1}" for i in range(50)]
    codes = await asyncio.gather(*[_reset(client, email, ip) for ip in ips])
    # 10 par email, toutes IP
    assert codes.count(400) <= 10
    assert codes.count(400) + codes.count(429) == 50


async def test_reset_code_burned_after_cap(client: AsyncClient) -> None:
    from jenny.api.auth.email_verification import code_expiry, hash_code

    email = await _user(
        password_reset_code_hash=hash_code("424242"), password_reset_expires_at=code_expiry()
    )
    for n in range(10):
        assert await _reset(client, email, f"203.0.113.{n // 5 + 1}") == 400
    async with async_session_factory() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
    # trop de faux : code mort
    assert user.password_reset_code_hash is None
    assert await _reset(client, email, "203.0.113.200", code="424242") == 429
    # fenêtre passée : toujours mort
    mw.reset_failures()
    if core_rl._redis is not None:
        await _wipe(core_rl._redis)
    assert await _reset(client, email, "203.0.113.200", code="424242") == 400


async def test_login_burst_capped(client: AsyncClient) -> None:
    email = await _user()

    async def _try() -> int:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "faux"},
            headers={"X-Forwarded-For": "198.51.100.40"},
        )
        return r.status_code

    codes = await asyncio.gather(*[_try() for _ in range(50)])
    assert codes.count(401) <= 10
    assert codes.count(401) + codes.count(429) == 50


async def test_login_ipv6_same_64_shares_counter(client: AsyncClient) -> None:
    email = await _user()
    codes = []
    for n in range(11):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "faux"},
            headers={"X-Forwarded-For": f"2001:db8:5:6::{n + 1:x}"},
        )
        codes.append(r.status_code)
    # même /64 : même client
    assert codes == [401] * 10 + [429]
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PWD},
        headers={"X-Forwarded-For": "2001:db8:5:7::1"},
    )
    assert r.status_code == 200


async def test_success_does_not_count_for_ip(client: AsyncClient, limiter) -> None:
    email = await _user()
    ip = {"X-Forwarded-For": "198.51.100.41"}
    body = {"email": email, "password": _PWD}
    for _ in range(limiter.rate_limit_auth_max_requests + 5):
        assert (await client.post("/api/v1/auth/login", json=body, headers=ip)).status_code == 200
    assert await mw.recent_failures("login_ip", "198.51.100.41", 60) == 0


async def test_verify_email_burst_capped(client: AsyncClient) -> None:
    from jenny.api.auth.email_verification import code_expiry, hash_code

    email = await _user(
        email_verified=False,
        email_verification_code_hash=hash_code("123456"),
        email_verification_expires_at=code_expiry(),
        email_verification_attempts=0,
    )

    async def _try() -> int:
        r = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": "000000"})
        return r.status_code

    # sous la taille du pool
    codes = await asyncio.gather(*[_try() for _ in range(12)])
    assert codes.count(400) <= MAX_VERIFY_ATTEMPTS
    assert codes.count(400) + codes.count(429) == 12
    async with async_session_factory() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verification_attempts == MAX_VERIFY_ATTEMPTS
    # le bon code aussi bloqué
    r = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": "123456"})
    assert r.status_code == 429
