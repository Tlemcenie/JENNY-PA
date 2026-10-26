"""Canaux : unicité entre salons, revendication."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.core.config import get_settings
from jenny.db.repositories.channel_account_repo import ChannelAccountRepository
from jenny.db.session import async_session_factory
from jenny.domain.models.audit_log import AuditLog
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.channel_account import ChannelAccount
from jenny.domain.models.user import User
from jenny.services import channel_credentials_service as creds_svc

pytestmark = pytest.mark.usefixtures("db_tables")


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    # vraie clé fernet
    monkeypatch.setattr(get_settings(), "master_key", Fernet.generate_key().decode())
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _salon(name: str) -> tuple[UUID, dict]:
    """Salon + owner, (id, auth)."""
    async with async_session_factory() as s, s.begin():
        biz = Business(name=name, slug=f"{name.lower()}-{uuid4().hex[:6]}")
        s.add(biz)
        await s.flush()
        user = User(email=f"{name.lower()}-{uuid4().hex[:6]}@x.com", email_verified=True)
        s.add(user)
        await s.flush()
        s.add(BusinessMember(user_id=user.id, business_id=biz.id, role="owner"))
        bid, uid, email = biz.id, user.id, user.email
    token = create_access_token(uid, email, [bid])
    return bid, {"Authorization": f"Bearer {token}"}


def _smtp(**extra) -> dict:
    return {
        "credentials": {
            "smtp_host": "smtp.resend.com",
            "smtp_username": "resend",
            "smtp_password": "re_secret",
            **extra,
        }
    }


def _wa(phone_id: str = "1112223334") -> dict:
    return {"credentials": {"phone_number_id": phone_id, "access_token": "EAAG-token"}}


async def _audit(bid: UUID, action: str) -> list[AuditLog]:
    async with async_session_factory() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.business_id == bid, AuditLog.action == action)
        )
        return list(rows.scalars().all())


async def test_generic_smtp_login_shared_by_two_salons(client: AsyncClient) -> None:
    _a, auth_a = await _salon("Alpha")
    _b, auth_b = await _salon("Beta")
    ra = await client.post("/api/v1/channels/email/connect", headers=auth_a, json=_smtp())
    rb = await client.post("/api/v1/channels/email/connect", headers=auth_b, json=_smtp())
    assert ra.status_code == 200, ra.text
    assert rb.status_code == 200, rb.text
    assert rb.json()["account"] == "resend"
    # mise à jour du 2e : ok aussi
    again = await client.post(
        "/api/v1/channels/email/connect", headers=auth_b, json=_smtp(smtp_password="re_new")
    )
    assert again.status_code == 200, again.text
    listed = (await client.get("/api/v1/channels", headers=auth_b)).json()
    email = next(c for c in listed if c["channel"] == "email")
    assert email["account"] == "resend" and email["outbound_ready"] is True


async def test_same_sender_address_not_blocked(client: AsyncClient) -> None:
    _a, auth_a = await _salon("Alpha")
    _b, auth_b = await _salon("Beta")
    body = _smtp(smtp_from_email="Contact@Franchise.fr")
    assert (
        await client.post("/api/v1/channels/email/connect", headers=auth_a, json=body)
    ).status_code == 200
    rb = await client.post("/api/v1/channels/email/connect", headers=auth_b, json=body)
    assert rb.status_code == 200, rb.text
    # identité = adresse expéditrice
    assert rb.json()["account"] == "contact@franchise.fr"


async def test_sender_resolved_without_fake_address(client: AsyncClient) -> None:
    a, auth_a = await _salon("Alpha")
    b, auth_b = await _salon("Beta")
    await client.post("/api/v1/channels/email/connect", headers=auth_a, json=_smtp())
    await client.post(
        "/api/v1/channels/email/connect",
        headers=auth_b,
        json=_smtp(smtp_username="moi@gmail.com", smtp_host="smtp.gmail.com"),
    )
    async with async_session_factory() as s:
        creds_a = await creds_svc.resolve(s, a, "email")
        creds_b = await creds_svc.resolve(s, b, "email")
    # jamais « uuid:resend »
    assert creds_a.smtp_from_email == ""
    assert creds_b.smtp_from_email == "moi@gmail.com"


async def test_whatsapp_conflict_is_a_logged_claim(client: AsyncClient) -> None:
    a, auth_a = await _salon("Alpha")
    b, auth_b = await _salon("Beta")
    assert (
        await client.post("/api/v1/channels/whatsapp/connect", headers=auth_a, json=_wa())
    ).status_code == 200

    r = await client.post("/api/v1/channels/whatsapp/connect", headers=auth_b, json=_wa())
    assert r.status_code == 409
    assert "revendication" in r.json()["detail"]
    assert "WhatsApp" in r.json()["detail"]
    # 2e essai : pas de doublon
    r2 = await client.post("/api/v1/channels/whatsapp/connect", headers=auth_b, json=_wa())
    assert r2.status_code == 409

    claims = await _audit(b, "channel.claim_requested")
    assert len(claims) == 1
    assert claims[0].meta["account"] == "…3334"
    assert "1112223334" not in claims[0].summary
    warned = await _audit(a, "channel.claimed_by_other")
    assert len(warned) == 1
    # le routage ne bouge pas
    async with async_session_factory() as s:
        repo = ChannelAccountRepository(s)
        assert await repo.get_business_for_channel("whatsapp", "1112223334") == a
        assert await repo.get_account(b, "whatsapp") is None
    # le vrai salon met à jour
    own = await client.post(
        "/api/v1/channels/whatsapp/connect",
        headers=auth_a,
        json={"credentials": {"phone_number_id": "1112223334", "access_token": "EAAG-new"}},
    )
    assert own.status_code == 200, own.text


async def test_routed_ids_stay_raw_others_scoped(client: AsyncClient) -> None:
    a, auth_a = await _salon("Alpha")
    await client.post("/api/v1/channels/whatsapp/connect", headers=auth_a, json=_wa("777"))
    await client.post("/api/v1/channels/email/connect", headers=auth_a, json=_smtp())
    async with async_session_factory() as s:
        rows = {
            r.channel: r.external_account_id
            for r in (
                await s.execute(select(ChannelAccount).where(ChannelAccount.business_id == a))
            ).scalars()
        }
    assert rows["whatsapp"] == "777"
    assert rows["email"] == f"{a}:resend"
