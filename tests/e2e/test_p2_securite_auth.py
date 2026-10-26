"""Frein de connexion : échecs seulement."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import jenny.domain.models  # noqa: F401
from jenny.api.auth.password_utils import hash_password
from jenny.api.main import create_app
from jenny.api.middleware import rate_limit as mw
from jenny.core import rate_limit as core_rl
from jenny.core.config import get_settings
from jenny.db.session import async_session_factory
from jenny.domain.models.user import User

pytestmark = pytest.mark.usefixtures("db_tables")

_PWD = "Demo!1234"


@pytest.fixture
def limiter(monkeypatch: pytest.MonkeyPatch):
    """Limiteur actif, mémoire seule."""
    s = get_settings()
    monkeypatch.setattr(s, "env", "dev")
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    monkeypatch.setattr(core_rl, "_redis", None)
    monkeypatch.setattr(core_rl, "_redis_unavailable", True)
    core_rl._local_hits.clear()
    mw.reset_failures()
    yield s
    core_rl._local_hits.clear()
    mw.reset_failures()


@pytest.fixture
async def client(limiter):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _user(email: str | None = None) -> str:
    email = email or f"gerant-{uuid4().hex[:6]}@salon.fr"
    async with async_session_factory() as s, s.begin():
        s.add(User(email=email, password_hash=hash_password(_PWD), email_verified=True))
    return email


async def _login(c: AsyncClient, email: str, pwd: str, ip: str = "203.0.113.1") -> int:
    r = await c.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
        headers={"X-Forwarded-For": ip},
    )
    return r.status_code


async def test_shared_demo_logs_in_30_times(client: AsyncClient) -> None:
    email = await _user("demo@jenny.ai")
    codes = [await _login(client, email, _PWD) for _ in range(30)]
    assert codes == [200] * 30


async def test_success_resets_the_counter(client: AsyncClient) -> None:
    email = await _user()
    assert [await _login(client, email, "faux") for _ in range(9)] == [401] * 9
    assert await _login(client, email, _PWD) == 200
    # remis à zéro
    assert [await _login(client, email, "faux") for _ in range(9)] == [401] * 9
    assert await _login(client, email, _PWD) == 200


async def test_ten_failures_lock_this_ip_only(client: AsyncClient) -> None:
    email = await _user()
    attacker = "198.51.100.7"
    assert [await _login(client, email, "faux", attacker) for _ in range(10)] == [401] * 10
    # même le bon mot de passe
    assert await _login(client, email, _PWD, attacker) == 429
    # le vrai gérant passe
    assert await _login(client, email, _PWD, "203.0.113.50") == 200


async def test_global_cap_per_email(client: AsyncClient) -> None:
    email = await _user()
    for n in range(5):
        ip = f"198.51.100.{n + 10}"
        codes = [await _login(client, email, "faux", ip) for _ in range(10)]
        assert codes == [401] * 10
    # 50 échecs : plafond email
    assert await _login(client, email, _PWD, "203.0.113.99") == 429


async def test_ip_cap_across_accounts(client: AsyncClient) -> None:
    ip = "198.51.100.200"
    limit = get_settings().rate_limit_auth_max_requests
    codes = [await _login(client, f"x{i}@y.fr", "faux", ip) for i in range(limit)]
    assert codes == [401] * limit
    assert await _login(client, "autre@y.fr", "faux", ip) == 429
    assert await _login(client, "autre@y.fr", "faux", "203.0.113.2") == 401


async def test_reset_counts_bad_codes_only(client: AsyncClient) -> None:
    email = await _user()
    r = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    bad = {"email": email, "code": "000001", "new_password": "Nouveau!123"}
    attacker = {"X-Forwarded-For": "198.51.100.9"}
    for _ in range(5):
        r = await client.post("/api/v1/auth/reset-password", json=bad, headers=attacker)
        assert r.status_code == 400
    r = await client.post("/api/v1/auth/reset-password", json=bad, headers=attacker)
    assert r.status_code == 429
    # autre ip : pas bloquée
    r = await client.post(
        "/api/v1/auth/reset-password", json=bad, headers={"X-Forwarded-For": "203.0.113.3"}
    )
    assert r.status_code == 400


async def test_429_carries_cors(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_login_max_requests", 1)
    head = {"Origin": "https://app.salon.fr", "X-Forwarded-For": "198.51.100.77"}
    body = {"email": "a@b.fr", "password": "x"}
    await client.post("/api/v1/auth/login", json=body, headers=head)
    r = await client.post("/api/v1/auth/login", json=body, headers=head)
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == "*"
    assert "Retry-After" in r.headers["access-control-expose-headers"]
