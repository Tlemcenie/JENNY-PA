"""Sécurité e2e : un salon ne touche jamais un autre salon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token, decode_token
from jenny.api.main import create_app
from jenny.core.config import get_settings
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.api_key import ApiKey
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.payment_record import PaymentRecord
from jenny.domain.models.user import User


@compiles(ARRAY, "sqlite")
def _array_as_json(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


def _bearer(user_id: UUID, email: str, bids: list[UUID]) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, email, bids)}"}


async def _salon(name: str) -> tuple[UUID, dict, str]:
    """Salon + owner, renvoie (id, auth, email)."""
    async with async_session_factory() as s, s.begin():
        biz = Business(name=name, slug=f"{name.lower()}-{uuid4().hex[:6]}")
        s.add(biz)
        await s.flush()
        email = f"{name.lower()}-{uuid4().hex[:6]}@x.com"
        user = User(email=email, full_name=name, email_verified=True)
        s.add(user)
        await s.flush()
        s.add(BusinessMember(user_id=user.id, business_id=biz.id, role="owner"))
        bid, uid = biz.id, user.id
    return bid, _bearer(uid, email, [bid]), email


async def _member(bid: UUID, role: str) -> dict:
    """Membre d'un salon existant."""
    async with async_session_factory() as s, s.begin():
        email = f"{role}-{uuid4().hex[:6]}@x.com"
        user = User(email=email, full_name=role, email_verified=True)
        s.add(user)
        await s.flush()
        s.add(BusinessMember(user_id=user.id, business_id=bid, role=role))
        uid = user.id
    return _bearer(uid, email, [bid])


async def _no_salon() -> dict:
    """Compte sans aucun salon."""
    async with async_session_factory() as s, s.begin():
        user = User(email=f"seul-{uuid4().hex[:6]}@x.com", email_verified=True)
        s.add(user)
        await s.flush()
        uid, email = user.id, user.email
    return _bearer(uid, email, [])


def _form(email: str = "client@x.com") -> dict:
    return {
        "form_id": "contact",
        "submitted_at": datetime.now(UTC).isoformat(),
        "full_name": "Claire",
        "email": email,
        "message": "Bonjour, une question.",
    }


async def _count_convs(bid: UUID) -> int:
    async with async_session_factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(Conversation)
                    .where(Conversation.business_id == bid)
                )
            ).scalar_one()
        )


# ── base de connaissances / messages ──


@pytest.mark.asyncio
async def test_knowledge_idor_closed(client: AsyncClient, db_tables: None) -> None:
    a, _auth_a, _ = await _salon("Alpha")
    _b, auth_b, _ = await _salon("Beta")
    for method, url, kw in [
        ("get", f"/api/v1/knowledge/entries/{a}", {}),
        ("get", f"/api/v1/knowledge/stats/{a}", {}),
        ("get", f"/api/v1/knowledge/search/{a}?q=prix", {}),
        ("delete", f"/api/v1/knowledge/entries/{a}/x", {}),
        ("post", "/api/v1/knowledge/text", {"json": {"business_id": str(a), "content": "pirate"}}),
    ]:
        r = await getattr(client, method)(url, headers=auth_b, **kw)
        assert r.status_code == 403, (url, r.text)
        anon = await getattr(client, method)(url, **kw)
        assert anon.status_code == 401, (url, anon.text)
    # compte sans salon : fermé
    r = await client.get(f"/api/v1/knowledge/entries/{a}", headers=await _no_salon())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_messages_idor_closed(client: AsyncClient, db_tables: None) -> None:
    a, auth_a, _ = await _salon("Alpha")
    _b, auth_b, _ = await _salon("Beta")
    assert (
        await client.get(f"/api/v1/messages/?business_id={a}", headers=auth_b)
    ).status_code == 403
    r = await client.get(f"/api/v1/messages/{uuid4()}?business_id={a}", headers=auth_b)
    assert r.status_code == 403
    assert (await client.get(f"/api/v1/messages/?business_id={a}")).status_code == 401
    own = await client.get(f"/api/v1/messages/?business_id={a}", headers=auth_a)
    assert own.status_code == 200, own.text


# ── ingestion ──


@pytest.mark.asyncio
async def test_ingest_ignores_foreign_business_id(client: AsyncClient, db_tables: None) -> None:
    a, _auth_a, _ = await _salon("Alpha")
    b, auth_b, _ = await _salon("Beta")
    r = await client.post(f"/api/v1/ingest/form?business_id={a}", headers=auth_b, json=_form())
    assert r.status_code == 201, r.text
    # atterrit chez Beta, jamais chez Alpha
    assert await _count_convs(a) == 0
    assert await _count_convs(b) == 1
    anon = await client.post(f"/api/v1/ingest/form?business_id={a}", json=_form())
    assert anon.status_code == 401
    email = {
        "message_id": "<m1@x>",
        "from_email": "c@x.com",
        "to_email": "salon@x.com",
        "subject": "Q",
        "text_body": "Bonjour",
        "sent_at": datetime.now(UTC).isoformat(),
    }
    assert (
        await client.post(f"/api/v1/ingest/email?business_id={a}", json=email)
    ).status_code == 401


@pytest.mark.asyncio
async def test_ingest_with_api_key(client: AsyncClient, db_tables: None) -> None:
    a, auth_a, _ = await _salon("Alpha")
    created = await client.post("/api/v1/api-keys", headers=auth_a, json={"name": "site"})
    assert created.status_code == 201, created.text
    key = {"X-API-Key": created.json()["secret"]}
    r = await client.post("/api/v1/ingest/form", headers=key, json=_form())
    assert r.status_code == 201, r.text
    assert await _count_convs(a) == 1
    bad = await client.post("/api/v1/ingest/form", headers={"X-API-Key": "sk_faux"}, json=_form())
    assert bad.status_code == 401
    # clé expirée : refusée
    async with async_session_factory() as s, s.begin():
        k = (await s.execute(select(ApiKey))).scalar_one()
        k.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    late = await client.post("/api/v1/ingest/form", headers=key, json=_form("autre@x.com"))
    assert late.status_code == 401


# ── chat ──


def _chat(conv: UUID | str, bid: UUID | str, **extra) -> dict:
    return {"conversation_id": str(conv), "business_id": str(bid), "message": "Bonjour", **extra}


@pytest.mark.asyncio
async def test_chat_cannot_target_other_salon(client: AsyncClient, db_tables: None) -> None:
    a, _auth_a, _ = await _salon("Alpha")
    _b, auth_b, _ = await _salon("Beta")
    r = await client.post("/api/v1/conversation/chat", headers=auth_b, json=_chat(uuid4(), a))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_chat_conversation_hijack_blocked(client: AsyncClient, db_tables: None) -> None:
    a, auth_a, _ = await _salon("Alpha")
    b, auth_b, _ = await _salon("Beta")
    ing = await client.post("/api/v1/ingest/form", headers=auth_a, json=_form())
    conv_a = ing.json()["conversation_id"]
    # anonyme : pas la conv d'un client connu
    anon = await client.post("/api/v1/conversation/chat", json=_chat(conv_a, a))
    assert anon.status_code == 403
    # autre salon, même via son propre id
    other = await client.post("/api/v1/conversation/chat", headers=auth_b, json=_chat(conv_a, b))
    assert other.status_code == 403
    # le salon lui-même : ok
    own = await client.post("/api/v1/conversation/chat", headers=auth_a, json=_chat(conv_a, a))
    assert own.status_code == 200, own.text


@pytest.mark.asyncio
async def test_chat_customer_scoping(client: AsyncClient, db_tables: None) -> None:
    a, auth_a, _ = await _salon("Alpha")
    _b, auth_b, _ = await _salon("Beta")
    await client.post("/api/v1/ingest/form", headers=auth_a, json=_form())
    cust_a = (await client.get("/api/v1/conversations", headers=auth_a)).json()["conversations"][0][
        "customer_id"
    ]
    assert cust_a
    b = _b
    # client d'Alpha via Beta : refusé
    r = await client.post(
        "/api/v1/conversation/chat", headers=auth_b, json=_chat(uuid4(), b, customer_id=cust_a)
    )
    assert r.status_code == 403
    # anonyme : fiche client ignorée
    conv = uuid4()
    anon = await client.post("/api/v1/conversation/chat", json=_chat(conv, a, customer_id=cust_a))
    assert anon.status_code == 200, anon.text
    async with async_session_factory() as s:
        row = await s.get(Conversation, conv)
    assert row is not None and row.customer_id is None


@pytest.mark.asyncio
async def test_status_anonymous_is_minimal(client: AsyncClient, db_tables: None) -> None:
    a, auth_a, _ = await _salon("Alpha")
    _b, auth_b, _ = await _salon("Beta")
    conv = uuid4()
    r = await client.post(
        "/api/v1/conversation/chat",
        json={"conversation_id": str(conv), "business_id": str(a), "message": "une coupe mardi"},
    )
    assert r.status_code == 200
    anon = (await client.get(f"/api/v1/conversation/status/{conv}")).json()
    assert "slots" not in anon and "current_intent" not in anon
    assert anon["turn_count"] >= 1
    owner = (await client.get(f"/api/v1/conversation/status/{conv}", headers=auth_a)).json()
    assert "slots" in owner
    other = (await client.get(f"/api/v1/conversation/status/{conv}", headers=auth_b)).json()
    assert other["status"] == "not_found"
    lonely = (
        await client.get(f"/api/v1/conversation/status/{conv}", headers=await _no_salon())
    ).json()
    assert lonely["status"] == "not_found"


# ── temps réel / LLM ──


@pytest.mark.asyncio
async def test_sse_without_business_forbidden(client: AsyncClient, db_tables: None) -> None:
    r = await client.get("/api/v1/realtime/stream", headers=await _no_salon())
    assert r.status_code == 403


# ── équipe ──


def _new_member(role: str, email: str | None = None) -> dict:
    return {
        "email": email or f"n-{uuid4().hex[:6]}@x.com",
        "full_name": "Nouveau",
        "password": "Pass!1234",
        "role": role,
    }


@pytest.mark.asyncio
async def test_members_role_rules(client: AsyncClient, db_tables: None) -> None:
    a, auth_owner, _ = await _salon("Alpha")
    _b, _auth_b, email_b = await _salon("Beta")
    agent = await _member(a, "agent")
    admin = await _member(a, "admin")
    url = "/api/v1/business/members"

    assert (await client.post(url, headers=agent, json=_new_member("member"))).status_code == 403
    assert (await client.post(url, headers=admin, json=_new_member("owner"))).status_code == 403
    assert (await client.post(url, headers=admin, json=_new_member("member"))).status_code == 201
    # compte d'un autre salon : jamais rattaché
    steal = await client.post(url, headers=auth_owner, json=_new_member("owner", email_b))
    assert steal.status_code == 409
    async with async_session_factory() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(BusinessMember)
                .join(User, User.id == BusinessMember.user_id)
                .where(User.email == email_b)
            )
        ).scalar_one()
    assert n == 1
    # déjà membre : rôle inchangé
    fresh = _new_member("agent")
    assert (await client.post(url, headers=auth_owner, json=fresh)).status_code == 201
    again = await client.post(url, headers=auth_owner, json={**fresh, "role": "owner"})
    assert again.status_code == 201 and again.json()["role"] == "agent"
    # réglages : owner/admin seulement
    patch = {"auto_reply_message": "Fermé"}
    assert (await client.patch("/api/v1/business/me", headers=agent, json=patch)).status_code == 403
    assert (await client.patch("/api/v1/business/me", headers=admin, json=patch)).status_code == 200


# ── résolution du salon par défaut ──


@pytest.mark.asyncio
async def test_default_business_is_deterministic(client: AsyncClient, db_tables: None) -> None:
    from jenny.api.routes.auth import _issue_token_for_user

    async with async_session_factory() as s, s.begin():
        old = Business(name="Ancien", slug=f"ancien-{uuid4().hex[:6]}")
        mine = Business(name="Le mien", slug=f"mien-{uuid4().hex[:6]}")
        s.add_all([old, mine])
        await s.flush()
        user = User(email=f"multi-{uuid4().hex[:6]}@x.com", email_verified=True)
        s.add(user)
        await s.flush()
        # simple membre ailleurs, owner chez lui
        s.add(BusinessMember(user_id=user.id, business_id=old.id, role="member"))
        s.add(BusinessMember(user_id=user.id, business_id=mine.id, role="owner"))
        uid, email, mine_id = user.id, user.email, mine.id
    async with async_session_factory() as s:
        u = await s.get(User, uid)
        token = await _issue_token_for_user(s, u)
    assert decode_token(token)["business_ids"][0] == str(mine_id)
    # token sans claim : même salon
    me = (await client.get("/api/v1/auth/me", headers=_bearer(uid, email, []))).json()
    assert me["business_id"] == str(mine_id) and me["role"] == "owner"


@pytest.mark.asyncio
async def test_google_callback_creates_business(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jenny.api.routes import auth as auth_mod

    profile = {"sub": "g-123", "email": "g@x.com", "name": "G", "email_verified": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "ga"})
        return httpx.Response(200, json=profile)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        auth_mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(get_settings(), "google_oauth_client_id", "cid")
    monkeypatch.setattr(get_settings(), "google_oauth_client_secret", "csecret")

    r = await client.get("/api/v1/auth/google/callback?code=abc")
    assert r.status_code == 200, r.text
    bids = decode_token(r.json()["access_token"])["business_ids"]
    assert len(bids) == 1  # salon créé
    # email non vérifié : refus
    profile.update({"sub": "g-456", "email": "h@x.com", "email_verified": False})
    r2 = await client.get("/api/v1/auth/google/callback?code=abc")
    assert r2.status_code == 400


# ── webhooks ──


@pytest.mark.asyncio
async def test_paypal_webhook_requires_signature(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jenny.api.routes import payment_webhooks as pw

    event = {
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "O-1", "status": "APPROVED"},
    }
    # non configuré : 503
    assert (await client.post("/api/v1/payments/paypal", json=event)).status_code == 503

    s = get_settings()
    monkeypatch.setattr(s, "paypal_webhook_id", "WH-1")
    monkeypatch.setattr(s, "paypal_client_id", "id")
    monkeypatch.setattr(s, "paypal_client_secret", "secret")
    a, _auth_a, _ = await _salon("Alpha")
    b, _auth_b, _ = await _salon("Beta")
    async with async_session_factory() as db, db.begin():
        for bid in (a, b):
            db.add(
                PaymentRecord(
                    business_id=bid, provider="paypal", external_id="O-1", status="CREATED"
                )
            )

    async def refuse(headers, raw):
        return False

    monkeypatch.setattr(pw, "verify_paypal_signature", refuse)
    assert (await client.post("/api/v1/payments/paypal", json=event)).status_code == 400

    async def accept(headers, raw):
        return True

    monkeypatch.setattr(pw, "verify_paypal_signature", accept)
    # même id chez 2 salons, sans salon : ignoré
    amb = await client.post("/api/v1/payments/paypal", json=event)
    assert amb.status_code == 200 and amb.json()["status"] == "ignored"
    # avec custom_id : seul ce salon bouge
    event["resource"]["custom_id"] = str(b)
    ok = await client.post("/api/v1/payments/paypal", json=event)
    assert ok.json()["status"] == "ok"
    async with async_session_factory() as db:
        rows = {
            r.business_id: r.status
            for r in (await db.execute(select(PaymentRecord))).scalars().all()
        }
    assert rows[b] == "APPROVED" and rows[a] == "CREATED"


@pytest.mark.asyncio
async def test_snapchat_needs_shared_secret(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"messages": [{"id": "s1", "sender_id": "u", "text": "Yo", "timestamp": "1"}]}
    assert (await client.post("/api/v1/webhooks/snapchat", json=payload)).status_code == 503
    monkeypatch.setattr(get_settings(), "snapchat_webhook_secret", "snap")
    wrong = await client.post(
        "/api/v1/webhooks/snapchat", json=payload, headers={"X-Jenny-Webhook-Secret": "nope"}
    )
    assert wrong.status_code == 401
    ok = await client.post(
        "/api/v1/webhooks/snapchat", json=payload, headers={"X-Jenny-Webhook-Secret": "snap"}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "ignored"  # pas de salon


@pytest.mark.asyncio
async def test_prod_ignores_skip_meta_signature(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "env", "prod")
    monkeypatch.setattr(s, "rate_limit_enabled", False)
    monkeypatch.setattr(s, "skip_meta_signature", True)
    r = await client.post("/api/v1/webhooks/whatsapp", json={"object": "whatsapp_business_account"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_prod_unroutable_whatsapp_is_ignored(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import hmac
    import json

    a, _auth, _ = await _salon("Alpha")
    s = get_settings()
    monkeypatch.setattr(s, "env", "prod")
    monkeypatch.setattr(s, "rate_limit_enabled", False)
    monkeypatch.setattr(s, "facebook_app_secret", "meta")
    monkeypatch.setattr(s, "default_business_id", str(a))
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "1",
                                    "phone_number_id": "INCONNU",
                                },
                                "contacts": [],
                                "messages": [],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    sig = "sha256=" + hmac.new(b"meta", body, hashlib.sha256).hexdigest()
    r = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    # pas de repli en prod
    assert r.json() == {"status": "ignored", "reason": "no_channel_account_mapping"}
