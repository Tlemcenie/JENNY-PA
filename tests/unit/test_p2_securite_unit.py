"""Sécurité passe 2 : préfixes publics, config."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from jenny.api.main import create_app
from jenny.api.middleware.rate_limit import LOGIN_PATH, _rule_for
from jenny.api.middleware.security import _is_public
from jenny.core.config import InsecureConfigError, Settings, check_prod_secrets, get_settings


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_public_prefix_is_public_and_limited() -> None:
    s = _s(env="prod")
    for path in ("/api/v1/public/chat/salon-lea", "/api/v1/public/booking/salon-lea/slots"):
        assert _is_public(path)
        assert _rule_for(path, "POST", s) == ("ingest", s.rate_limit_max_requests)
    # pas un préfixe voisin
    assert not _is_public("/api/v1/publicite")
    assert _rule_for("/api/v1/publicite", "GET", s) is None


def test_payments_webhooks_limited() -> None:
    s = _s()
    assert _rule_for("/api/v1/payments/paypal/webhook", "POST", s) == (
        "ingest",
        s.rate_limit_max_requests,
    )


def test_login_has_its_own_bucket() -> None:
    s = _s(rate_limit_login_max_requests=60, rate_limit_auth_max_requests=20)
    assert _rule_for(LOGIN_PATH, "POST", s) == ("auth_login", 60)
    assert _rule_for("/api/v1/auth/register", "POST", s) == ("auth", 20)


def test_prod_refuses_example_jwt_secret() -> None:
    key = Fernet.generate_key().decode()
    with pytest.raises(InsecureConfigError):
        check_prod_secrets(
            _s(env="prod", jwt_secret="CHANGE_ME__run_openssl_rand_hex_32", master_key=key)
        )
    check_prod_secrets(_s(env="prod", jwt_secret="a" * 64, master_key=key))


@pytest.mark.usefixtures("db_tables")
async def test_public_routes_open_when_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "require_auth", True)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # salon inconnu, pas 401
        r = await c.get("/api/v1/public/chat/salon-inconnu/config")
        assert r.status_code == 404
        assert (await c.get("/api/v1/conversations")).status_code == 401
