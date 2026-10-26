"""Sécurité : config prod, isolation, débit, signatures."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from jenny.api.dependencies import CurrentPrincipal, resolve_business_id
from jenny.core import rate_limit as core_rl
from jenny.core.config import (
    DEFAULT_JWT_SECRET,
    InsecureConfigError,
    Settings,
    check_prod_secrets,
    get_settings,
)

# ── config prod ──


def _prod(**kw) -> Settings:
    return Settings(_env_file=None, env="prod", **kw)


def test_prod_refuses_default_jwt_and_missing_master_key():
    with pytest.raises(InsecureConfigError) as exc:
        check_prod_secrets(_prod())
    msg = str(exc.value)
    assert "JENNY_JWT_SECRET" in msg and "JENNY_MASTER_KEY" in msg


def test_prod_refuses_invalid_master_key():
    with pytest.raises(InsecureConfigError, match="invalide"):
        check_prod_secrets(_prod(jwt_secret="x" * 40, master_key="pas-une-cle"))


def test_prod_ok_with_real_secrets():
    s = _prod(jwt_secret="x" * 40, master_key=Fernet.generate_key().decode() + "\n")
    check_prod_secrets(s)


def test_dev_never_refused():
    check_prod_secrets(Settings(_env_file=None, env="dev", jwt_secret=DEFAULT_JWT_SECRET))


def test_get_settings_refuses_to_start_in_bad_prod(monkeypatch):
    monkeypatch.setenv("JENNY_ENV", "prod")
    monkeypatch.setenv("JENNY_JWT_SECRET", DEFAULT_JWT_SECRET)
    monkeypatch.setenv("JENNY_MASTER_KEY", "")
    # sans toucher au cache
    with pytest.raises(InsecureConfigError):
        get_settings.__wrapped__()


def test_prod_forces_auth_and_meta_signature():
    s = _prod(require_auth=False, skip_meta_signature=True)
    assert s.auth_required is True
    assert s.meta_signature_skipped is False
    d = Settings(_env_file=None, env="dev", skip_meta_signature=True)
    assert d.auth_required is False and d.meta_signature_skipped is True


# ── helper d'isolation ──


def _p(bid=None, user=True) -> CurrentPrincipal:
    return CurrentPrincipal(user_id=uuid4() if user else None, business_id=bid, email=None)


def test_resolve_same_business_ok():
    bid = uuid4()
    assert resolve_business_id(_p(bid), bid) == bid
    assert resolve_business_id(_p(bid), str(bid)) == bid
    assert resolve_business_id(_p(bid)) == bid


def test_resolve_other_business_forbidden():
    with pytest.raises(HTTPException) as exc:
        resolve_business_id(_p(uuid4()), uuid4())
    assert exc.value.status_code == 403


def test_resolve_principal_without_business_fails_closed():
    with pytest.raises(HTTPException) as exc:
        resolve_business_id(_p(None), uuid4())
    assert exc.value.status_code == 403


def test_resolve_anonymous():
    bid = uuid4()
    with pytest.raises(HTTPException) as exc:
        resolve_business_id(None, bid)
    assert exc.value.status_code == 401
    assert resolve_business_id(None, bid, allow_anonymous=True) == bid
    with pytest.raises(HTTPException):
        resolve_business_id(None, None, allow_anonymous=True)


# ── identifiants chiffrés ──


def test_credentials_without_master_key_refused(monkeypatch):
    from jenny.services import channel_credentials_service as svc

    monkeypatch.setattr(get_settings(), "master_key", "")
    monkeypatch.setattr(get_settings(), "allow_plaintext_credentials", False)
    with pytest.raises(svc.CredentialsStorageError) as exc:
        svc.encrypt_credentials({"access_token": "tok"})
    assert exc.value.status_code == 503
    assert "JENNY_MASTER_KEY" in exc.value.detail


def test_credentials_plaintext_opt_in_only_outside_prod(monkeypatch):
    from jenny.services import channel_credentials_service as svc

    monkeypatch.setattr(get_settings(), "master_key", "")
    monkeypatch.setattr(get_settings(), "allow_plaintext_credentials", True)
    assert svc.encrypt_credentials({"a": "b"}) == {"a": "b"}
    monkeypatch.setattr(get_settings(), "env", "prod")
    with pytest.raises(svc.CredentialsStorageError):
        svc.encrypt_credentials({"a": "b"})


def test_credentials_invalid_master_key_refused(monkeypatch):
    from jenny.services import channel_credentials_service as svc

    monkeypatch.setattr(get_settings(), "master_key", "nope")
    with pytest.raises(svc.CredentialsStorageError):
        svc.encrypt_credentials({"a": "b"})
    # lecture : vide, pas de crash
    assert svc.decrypt_credentials({"__enc__": "x"}) == {}


# ── limitation de débit ──


@pytest.fixture
def limiter(monkeypatch):
    """Limiteur actif, mémoire seule, petits plafonds."""
    from jenny.api.middleware import rate_limit as mw

    s = Settings(
        _env_file=None,
        env="dev",
        rate_limit_max_requests=50,
        rate_limit_auth_max_requests=2,
        rate_limit_chat_max_requests=3,
        rate_limit_chat_business_max_requests=2,
        rate_limit_proxy_hops=1,
    )
    monkeypatch.setattr(mw, "get_settings", lambda: s)
    monkeypatch.setattr(core_rl, "_redis", None)
    monkeypatch.setattr(core_rl, "_redis_unavailable", True)
    core_rl._local_hits.clear()
    yield s
    core_rl._local_hits.clear()


def _limited_app() -> FastAPI:
    from jenny.api.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict:
        return {"ok": True}

    @app.get("/api/v1/auth/me")
    async def me() -> dict:
        return {"ok": True}

    @app.post("/api/v1/conversation/chat")
    async def chat() -> dict:
        return {"ok": True}

    @app.get("/api/v1/other")
    async def other() -> dict:
        return {"ok": True}

    return app


async def test_auth_rate_limited_per_ip(limiter):
    async with AsyncClient(transport=ASGITransport(app=_limited_app()), base_url="http://t") as c:
        codes = [(await c.post("/api/v1/auth/login")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = await c.post("/api/v1/auth/login")
        assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
        # lecture /me : seau à part
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        # hors périmètre : jamais limité
        others = [(await c.get("/api/v1/other")).status_code for _ in range(5)]
        assert others == [200] * 5


async def test_chat_rate_limited_per_ip(limiter):
    async with AsyncClient(transport=ASGITransport(app=_limited_app()), base_url="http://t") as c:
        codes = [(await c.post("/api/v1/conversation/chat")).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]


async def test_spoofed_forwarded_for_does_not_bypass(limiter):
    async with AsyncClient(transport=ASGITransport(app=_limited_app()), base_url="http://t") as c:
        codes = []
        for i in range(3):
            # IP forgée devant, vraie IP derrière
            r = await c.post(
                "/api/v1/auth/login", headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"}
            )
            codes.append(r.status_code)
        assert codes == [200, 200, 429]


async def test_business_chat_limit(limiter):
    from jenny.api.middleware.rate_limit import enforce_business_chat_limit

    bid = uuid4()
    await enforce_business_chat_limit(bid)
    await enforce_business_chat_limit(bid)
    with pytest.raises(HTTPException) as exc:
        await enforce_business_chat_limit(bid)
    assert exc.value.status_code == 429
    # autre salon : pas touché
    await enforce_business_chat_limit(uuid4())


async def test_limiter_off_in_test_env(monkeypatch):
    from jenny.api.middleware import rate_limit as mw

    s = Settings(_env_file=None, env="test", rate_limit_auth_max_requests=1)
    monkeypatch.setattr(mw, "get_settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=_limited_app()), base_url="http://t") as c:
        codes = [(await c.post("/api/v1/auth/login")).status_code for _ in range(3)]
    assert codes == [200, 200, 200]


# ── signatures webhooks ──


def test_twitter_signature():
    from jenny.api.routes.webhooks import verify_twitter_signature

    body = b'{"for_user_id": "1"}'
    digest = hmac.new(b"consumer", body, hashlib.sha256).digest()
    good = "sha256=" + base64.b64encode(digest).decode()
    assert verify_twitter_signature(body, good, "consumer")
    assert not verify_twitter_signature(body + b" ", good, "consumer")
    assert not verify_twitter_signature(body, None, "consumer")
    assert not verify_twitter_signature(body, good, "")


def test_default_business_fallback_never_in_prod():
    from jenny.api.routes.webhooks import _fallback_business

    bid = uuid4()
    dev = Settings(_env_file=None, env="dev", default_business_id=str(bid))
    assert _fallback_business(dev, "whatsapp", "x") == bid
    assert _fallback_business(Settings(_env_file=None, env="dev"), "whatsapp", "x") is None
    prod = _prod(default_business_id=str(bid))
    assert _fallback_business(prod, "whatsapp", "x") is None


async def test_paypal_signature_sends_raw_event(monkeypatch):
    from jenny.api.routes import payment_webhooks as pw

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok"})
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        pw.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(get_settings(), "paypal_webhook_id", "WH-1")
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "t-1",
        "paypal-transmission-sig": "sig",
        "paypal-transmission-time": "2026-01-01T00:00:00Z",
    }
    raw = b'{"id":"WH-EV","event_type":"CHECKOUT.ORDER.APPROVED","resource":{"id":"O-1"}}'
    assert await pw.verify_paypal_signature(headers, raw) is True
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["webhook_id"] == "WH-1"
    assert seen["body"]["webhook_event"]["resource"]["id"] == "O-1"
    # en-tête manquant : refus direct
    assert await pw.verify_paypal_signature({}, raw) is False
