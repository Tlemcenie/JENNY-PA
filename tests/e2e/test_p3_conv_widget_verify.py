"""verify-email : jamais de jeton sans code."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import jenny.domain.models  # noqa: F401
from jenny.api.auth.email_verification import code_expiry, hash_code
from jenny.api.auth.password_utils import hash_password
from jenny.api.main import create_app
from jenny.db.session import async_session_factory
from jenny.domain.models.user import User

pytestmark = pytest.mark.usefixtures("db_tables")

_PWD = "Demo!1234"


@pytest.fixture
async def client():
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


async def _verify(c: AsyncClient, email: str, code: str):
    return await c.post("/api/v1/auth/verify-email", json={"email": email, "code": code})


def _no_token(r) -> None:
    assert r.status_code == 409, r.text
    assert "access_token" not in r.json()


async def test_verified_account_wrong_code_no_token(client: AsyncClient) -> None:
    email = await _user()
    _no_token(await _verify(client, email, "0000"))


async def test_google_account_no_token(client: AsyncClient) -> None:
    email = await _user(password_hash=None, google_sub=f"g-{uuid4().hex}")
    _no_token(await _verify(client, email, "123456"))


async def test_after_reset_no_token(client: AsyncClient) -> None:
    email = await _user(email_verified=False)
    r = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    code = r.json()["debug_code"]
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "code": code, "new_password": "Nouveau!123"},
    )
    assert r.status_code == 200, r.text
    # reset : adresse prouvée
    _no_token(await _verify(client, email, "000000"))
    _no_token(await _verify(client, email, code))


async def test_good_code_once_then_refused(client: AsyncClient) -> None:
    email = await _user(
        email_verified=False,
        email_verification_code_hash=hash_code("123456"),
        email_verification_expires_at=code_expiry(),
        email_verification_attempts=0,
    )
    r = await _verify(client, email, "123456")
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    # rejouer le code : refus
    _no_token(await _verify(client, email, "123456"))
    async with async_session_factory() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verified is True
    assert user.email_verification_code_hash is None


async def test_unknown_email_generic(client: AsyncClient) -> None:
    r = await _verify(client, f"nobody-{uuid4().hex[:6]}@salon.fr", "123456")
    assert r.status_code == 400
    assert "access_token" not in r.json()
