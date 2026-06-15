"""Tests e2e : console admin (super-admin) + calendrier (rendez-vous).

Valide le gating super-admin, les endpoints d'administration, et le CRUD des
rendez-vous — sur le schéma SQLite de test.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401 — enregistre les modèles
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.user import User

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _auth(client: AsyncClient, email: str) -> tuple[dict, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "User", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


async def _make_superuser(email: str) -> None:
    async with async_session_factory() as s, s.begin():
        await s.execute(update(User).where(User.email == email).values(is_superuser=True))


# ── Admin ────────────────────────────────────────────────────────────────────


class TestAdmin:
    @pytest.mark.asyncio
    async def test_non_superuser_forbidden(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "normal@x.com")
        for path in ("/api/v1/admin/overview", "/api/v1/admin/businesses", "/api/v1/admin/users"):
            r = await client.get(path, headers=headers)
            assert r.status_code == 403, f"{path} -> {r.status_code}"

    @pytest.mark.asyncio
    async def test_superuser_can_manage(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "boss@x.com")
        await _make_superuser("boss@x.com")
        # /auth/me expose le flag
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        assert me["is_superuser"] is True

        ov = (await client.get("/api/v1/admin/overview", headers=headers)).json()
        assert ov["users"] >= 1 and ov["businesses"] >= 1

        bizs = (await client.get("/api/v1/admin/businesses", headers=headers)).json()
        assert len(bizs) >= 1
        # Suspendre puis réactiver une entreprise
        bid = bizs[0]["id"]
        r = await client.patch(
            f"/api/v1/admin/businesses/{bid}/active", headers=headers, json={"is_active": False}
        )
        assert r.status_code == 200 and r.json()["is_active"] is False

        users = (await client.get("/api/v1/admin/users", headers=headers)).json()
        assert any(u["is_superuser"] for u in users)

    @pytest.mark.asyncio
    async def test_cannot_self_demote(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "boss2@x.com")
        await _make_superuser("boss2@x.com")
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        r = await client.patch(
            f"/api/v1/admin/users/{me['id']}/superuser", headers=headers, json={"is_superuser": False}
        )
        assert r.status_code == 400  # interdit de retirer ses propres droits


# ── Calendrier / rendez-vous ───────────────────────────────────────────────


class TestAppointments:
    @pytest.mark.asyncio
    async def test_crud(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "cal@x.com")
        # Créer
        r = await client.post(
            "/api/v1/appointments",
            headers=headers,
            json={
                "title": "Essayage robe",
                "start_at": "2026-06-20T10:00:00Z",
                "end_at": "2026-06-20T10:30:00Z",
                "location": "Boutique",
            },
        )
        assert r.status_code == 201, r.text
        appt = r.json()
        assert appt["title"] == "Essayage robe" and appt["status"] == "scheduled"
        aid = appt["id"]

        # Lister dans la fenêtre
        listed = (
            await client.get(
                "/api/v1/appointments?start=2026-06-01T00:00:00Z&end=2026-06-30T23:59:59Z",
                headers=headers,
            )
        ).json()
        assert listed["total"] == 1 and listed["appointments"][0]["id"] == aid

        # Hors fenêtre → vide
        out = (
            await client.get(
                "/api/v1/appointments?start=2026-07-01T00:00:00Z&end=2026-07-31T00:00:00Z",
                headers=headers,
            )
        ).json()
        assert out["total"] == 0

        # Mettre à jour le statut
        upd = await client.patch(
            f"/api/v1/appointments/{aid}", headers=headers, json={"status": "confirmed"}
        )
        assert upd.status_code == 200 and upd.json()["status"] == "confirmed"

        # Supprimer
        d = await client.delete(f"/api/v1/appointments/{aid}", headers=headers)
        assert d.status_code == 200
        empty = (await client.get("/api/v1/appointments", headers=headers)).json()
        assert empty["total"] == 0

    @pytest.mark.asyncio
    async def test_end_before_start_rejected(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "cal2@x.com")
        r = await client.post(
            "/api/v1/appointments",
            headers=headers,
            json={
                "title": "Invalide",
                "start_at": "2026-06-20T11:00:00Z",
                "end_at": "2026-06-20T10:00:00Z",
            },
        )
        assert r.status_code == 400
