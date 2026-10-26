"""KB réelle suivie après PATCH /business/me ou l'équipe."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from jenny.api.main import create_app
from jenny.db.session import async_session_factory
from jenny.domain.models import Business
from jenny.rag import kb_sync

_PASSWORD = "Strong#1234"
HOURS = {"tue": ["09:00", "19:00"], "sat": ["09:00", "17:00"]}


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Synchro branchée, encodeur évité."""
    seen: list[UUID] = []

    async def fake_refresh(business_id: UUID) -> dict:
        seen.append(business_id)
        return {}

    # SQLite en test : on fait comme Postgres
    monkeypatch.setattr(kb_sync, "_app_engine", lambda _s: True)
    monkeypatch.setattr(kb_sync, "run_refresh", fake_refresh)
    monkeypatch.setattr(kb_sync, "DELAY_S", 0.0)
    return seen


async def _auth(client: AsyncClient, email: str) -> tuple[dict, UUID]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Boss", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, UUID(bid)


@pytest.mark.asyncio
async def test_patch_horaires_relance_la_synchro(
    client: AsyncClient, db_tables: None, calls: list[UUID]
) -> None:
    headers, bid = await _auth(client, "kb-suivi-horaires@x.com")
    await kb_sync.wait_idle()
    calls.clear()
    r = await client.patch("/api/v1/business/me", headers=headers, json={"business_hours": HOURS})
    assert r.status_code == 200, r.text
    await kb_sync.wait_idle()
    assert calls == [bid]


@pytest.mark.asyncio
async def test_patch_acompte_et_contact(
    client: AsyncClient, db_tables: None, calls: list[UUID]
) -> None:
    headers, bid = await _auth(client, "kb-suivi-acompte@x.com")
    await kb_sync.wait_idle()
    calls.clear()
    body = {"deposit_enabled": True, "deposit_percent": 40, "phone": "01 02 03 04 05"}
    assert (
        await client.patch("/api/v1/business/me", headers=headers, json=body)
    ).status_code == 200
    await kb_sync.wait_idle()
    assert calls == [bid]


@pytest.mark.asyncio
async def test_champ_sans_fiche_rien(
    client: AsyncClient, db_tables: None, calls: list[UUID]
) -> None:
    headers, _bid = await _auth(client, "kb-suivi-nom@x.com")
    await kb_sync.wait_idle()
    calls.clear()
    r = await client.patch("/api/v1/business/me", headers=headers, json={"sla_minutes": 45})
    assert r.status_code == 200, r.text
    # même valeur : pas un changement
    await client.patch("/api/v1/business/me", headers=headers, json={"business_hours": None})
    await kb_sync.wait_idle()
    assert calls == []


@pytest.mark.asyncio
async def test_equipe_ajoutee_relance(
    client: AsyncClient, db_tables: None, calls: list[UUID]
) -> None:
    headers, bid = await _auth(client, "kb-suivi-equipe@x.com")
    await kb_sync.wait_idle()
    calls.clear()
    r = await client.post("/api/v1/staff", headers=headers, json={"display_name": "Nora"})
    assert r.status_code in (200, 201), r.text
    await kb_sync.wait_idle()
    assert calls == [bid]


@pytest.mark.asyncio
async def test_rollback_rien_et_commits_groupes(
    db_tables: None, calls: list[UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    # petit délai : commits regroupés
    monkeypatch.setattr(kb_sync, "DELAY_S", 0.2)
    async with async_session_factory() as db:
        biz = Business(name="Salon", slug="salon-suivi", business_hours=None)
        db.add(biz)
        await db.commit()
        bid = biz.id
    await kb_sync.wait_idle()
    calls.clear()
    async with async_session_factory() as db:
        biz = (await db.execute(select(Business).where(Business.id == bid))).scalar_one()
        biz.business_hours = HOURS
        await db.flush()
        await db.rollback()
    await kb_sync.wait_idle()
    assert calls == []
    async with async_session_factory() as db:
        biz = (await db.execute(select(Business).where(Business.id == bid))).scalar_one()
        biz.business_hours = HOURS
        await db.commit()
        biz.deposit_percent = 50
        await db.commit()
    # deux commits proches : une passe
    await kb_sync.wait_idle()
    assert calls == [bid]


@pytest.mark.asyncio
async def test_vraie_passe_sur_sqlite_sans_effet(db_tables: None) -> None:
    async with async_session_factory() as db:
        biz = Business(name="Salon", slug="salon-sqlite", business_hours=HOURS)
        db.add(biz)
        await db.commit()
        bid = biz.id
    # pas de pgvector : rien
    assert await kb_sync.run_refresh(bid) is None


def test_branche_par_l_appli() -> None:
    from jenny.api.routes import prestations

    # importé avec les routes
    assert prestations.kb_sync is kb_sync
