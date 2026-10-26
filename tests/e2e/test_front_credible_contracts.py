"""Contrats d'API dont dépendent les pages du front."""

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


async def _owner_headers(client: AsyncClient, email: str = "front@salon.com") -> dict[str, str]:
    """Compte vérifié, prêt à l'emploi."""
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Salon Front", "email": email, "password": _PASSWORD},
    )
    assert r.status_code in (200, 201, 202), r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    return {"Authorization": f"Bearer {rv.json()['access_token']}"}


@pytest.mark.asyncio
async def test_insights_periods_match_front(client: AsyncClient, db_tables: None) -> None:
    """Le front envoie 7, 30 ou 90 jours."""
    h = await _owner_headers(client)
    for days in (7, 30, 90):
        r = await client.get(f"/api/v1/insights?days={days}", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        # une vraie série, un point par jour
        assert len(body["messages_last_7_days"]) == days
        assert all(p["count"] == 0 for p in body["messages_last_7_days"])
    # l'ancien « Tout » (1095) cassait la page
    bad = await client.get("/api/v1/insights?days=1095", headers=h)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_saves_sector_tone_and_hours(client: AsyncClient, db_tables: None) -> None:
    """Persona fusionnée + horaires, comme l'onboarding."""
    h = await _owner_headers(client)

    step1 = await client.patch(
        "/api/v1/business/me",
        headers=h,
        json={
            "name": "Maison Lila",
            "description": "Coloriste",
            "persona": {"sector": "Coiffure mixte"},
        },
    )
    assert step1.status_code == 200, step1.text
    persona = step1.json()["persona"]
    assert persona["sector"] == "Coiffure mixte"

    hours = {
        "mon": None,
        "tue": ["09:00", "19:00"],
        "wed": ["09:00", "19:00"],
        "thu": ["09:00", "19:00"],
        "fri": ["09:00", "20:00"],
        "sat": ["09:00", "18:00"],
        "sun": None,
    }
    step3 = await client.patch("/api/v1/business/me", headers=h, json={"business_hours": hours})
    assert step3.status_code == 200, step3.text

    # le front renvoie la persona fusionnée
    step5 = await client.patch(
        "/api/v1/business/me", headers=h, json={"persona": {**persona, "tone": "chaleureux"}}
    )
    assert step5.status_code == 200, step5.text

    biz = (await client.get("/api/v1/business/me", headers=h)).json()
    assert biz["name"] == "Maison Lila"
    assert biz["persona"]["sector"] == "Coiffure mixte"
    assert biz["persona"]["tone"] == "chaleureux"
    assert biz["business_hours"]["mon"] is None
    assert biz["business_hours"]["fri"] == ["09:00", "20:00"]


class _NoVectorKB:
    """Base vide, sans modèle d'embedding."""

    def __init__(self, **_kw) -> None:
        pass

    async def list_entries(self) -> list:
        return []

    async def add_text(self, **_kw) -> None:
        raise RuntimeError("pas de store vectoriel en test")


@pytest.mark.asyncio
async def test_seed_coiffeur_is_idempotent(
    client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le bouton « modèle coiffeur » peut être recliqué."""
    # évite de charger mpnet
    monkeypatch.setattr("jenny.api.routes.prestations.KnowledgeBase", _NoVectorKB)
    h = await _owner_headers(client)
    empty = (await client.get("/api/v1/prestations", headers=h)).json()
    assert empty["total"] == 0

    first = await client.post("/api/v1/prestations/seed-coiffeur", headers=h)
    assert first.status_code == 200, first.text
    created = first.json()["prestations"]
    assert created > 0

    again = await client.post("/api/v1/prestations/seed-coiffeur", headers=h)
    assert again.status_code == 200
    assert again.json()["prestations"] == 0

    listed = (await client.get("/api/v1/prestations", headers=h)).json()
    assert listed["total"] == created


@pytest.mark.asyncio
async def test_dashboard_side_endpoints(client: AsyncClient, db_tables: None) -> None:
    """Cartes du dashboard et d'analytics."""
    h = await _owner_headers(client)

    conv = await client.get("/api/v1/conversations?sort_by=recent&limit=6", headers=h)
    assert conv.status_code == 200, conv.text
    assert conv.json()["conversations"] == []

    stats = await client.get("/api/v1/conversations/stats", headers=h)
    assert stats.status_code == 200
    assert stats.json()["awaiting"] == 0

    gaps = await client.get("/api/v1/knowledge-gaps?status=open", headers=h)
    assert gaps.status_code == 200
    assert gaps.json() == {"gaps": [], "total": 0}

    for days in (7, 30, 90):
        salon = await client.get(f"/api/v1/salon/stats?range_days={days}", headers=h)
        assert salon.status_code == 200, salon.text
        assert salon.json()["appointments_total"] == 0

    channels = await client.get("/api/v1/channels", headers=h)
    assert channels.status_code == 200
    rows = channels.json()
    assert rows, "au moins un canal listé"
    for row in rows:
        assert {"channel", "label", "connected", "builtin"} <= set(row)
