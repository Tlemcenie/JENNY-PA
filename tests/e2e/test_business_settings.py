"""Test : les réglages salon (acompte, rappels, fidélité) font l'aller-retour API.

Régression : ces champs existaient en base + front mais la route /business/me ne
les exposait pas → la page de réglages ne les sauvegardait pas (capté en live).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import engine

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncClient:
    from jenny.engine.factory import reset_engine

    reset_engine()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


@pytest.mark.asyncio
async def test_business_settings_roundtrip(client: AsyncClient, db_tables: None) -> None:
    email = "boss@salon.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Salon", "email": email, "password": _PASSWORD},
    )
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}

    # Valeurs par défaut exposées.
    biz = (await client.get("/api/v1/business/me", headers=headers)).json()
    assert biz["reminder_lead_minutes"] == 60
    assert biz["day_reminder_lead_hours"] == 24
    assert biz["loyalty_threshold"] == 10
    assert biz["deposit_enabled"] is False

    # PATCH → persistance.
    up = await client.patch(
        "/api/v1/business/me",
        headers=headers,
        json={
            "deposit_enabled": True, "deposit_percent": 40,
            "reminder_lead_minutes": 120, "day_reminder_lead_hours": 48,
            "loyalty_threshold": 8,
        },
    )
    assert up.status_code == 200, up.text
    b = up.json()
    assert b["deposit_enabled"] is True and b["deposit_percent"] == 40
    assert b["reminder_lead_minutes"] == 120 and b["day_reminder_lead_hours"] == 48
    assert b["loyalty_threshold"] == 8

    # Relecture indépendante → bien persisté.
    biz2 = (await client.get("/api/v1/business/me", headers=headers)).json()
    assert biz2["reminder_lead_minutes"] == 120 and biz2["loyalty_threshold"] == 8
