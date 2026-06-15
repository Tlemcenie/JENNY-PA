"""Tests e2e (batch 3) : mot de passe oublié, export .ics, recherche globale,
réservation publique en ligne.

Couvre les fonctionnalités back ajoutées pour le lot « au moins 10 » :
- ``/auth/forgot-password`` + ``/auth/reset-password`` (cycle complet)
- ``/appointments/export.ics`` (export iCalendar)
- ``/search`` (recherche transversale conversations/clients/RDV)
- ``/public/booking/{slug}`` (infos, créneaux, réservation, anti-doublon)

Exécutés sur le schéma SQLite de test (aucune dépendance Postgres/Ollama).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401 — enregistre les modèles
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import engine

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
        json={"full_name": "Boss", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


def _next_weekday(days_ahead: int = 14) -> date:
    """Premier lundi au moins ``days_ahead`` jours dans le futur (horaires par défaut lun-ven)."""
    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() != 0:  # 0 = lundi
        d += timedelta(days=1)
    return d


# ── Mot de passe oublié ────────────────────────────────────────────────────


class TestForgotPassword:
    @pytest.mark.asyncio
    async def test_full_reset_cycle(self, client: AsyncClient, db_tables: None) -> None:
        email = "reset@x.com"
        await _auth(client, email)

        # Demande de réinitialisation → code (debug en test).
        fp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert fp.status_code == 200, fp.text
        reset_code = fp.json()["debug_code"]

        # Réinitialise avec le nouveau mot de passe.
        new_pw = "Brandnew#2026"
        rp = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": email, "code": reset_code, "new_password": new_pw},
        )
        assert rp.status_code == 200 and rp.json()["status"] == "reset", rp.text

        # L'ancien mot de passe ne marche plus, le nouveau oui.
        old = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert old.status_code == 401
        new = await client.post("/api/v1/auth/login", json={"email": email, "password": new_pw})
        assert new.status_code == 200, new.text

    @pytest.mark.asyncio
    async def test_forgot_unknown_email_is_generic(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        # Compte inexistant → réponse générique « sent » (pas de fuite d'existence).
        r = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@x.com"})
        assert r.status_code == 200 and r.json()["status"] == "sent"
        assert "debug_code" not in r.json()

    @pytest.mark.asyncio
    async def test_reset_bad_code_rejected(self, client: AsyncClient, db_tables: None) -> None:
        email = "reset2@x.com"
        await _auth(client, email)
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": email, "code": "000000", "new_password": "Whatever#123"},
        )
        assert r.status_code == 400


# ── Export iCalendar (.ics) ────────────────────────────────────────────────


class TestIcsExport:
    @pytest.mark.asyncio
    async def test_export_contains_event(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "ics@x.com")
        await client.post(
            "/api/v1/appointments",
            headers=headers,
            json={
                "title": "Consultation Dupont",
                "start_at": "2026-07-01T09:00:00Z",
                "end_at": "2026-07-01T09:30:00Z",
                "location": "Cabinet",
            },
        )
        r = await client.get("/api/v1/appointments/export.ics", headers=headers)
        assert r.status_code == 200, r.text
        assert "text/calendar" in r.headers["content-type"]
        body = r.text
        assert "BEGIN:VCALENDAR" in body and "END:VCALENDAR" in body
        assert "BEGIN:VEVENT" in body and "SUMMARY:Consultation Dupont" in body
        assert "DTSTART:20260701T090000Z" in body


# ── Recherche globale ──────────────────────────────────────────────────────


class TestGlobalSearch:
    @pytest.mark.asyncio
    async def test_finds_appointment(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "search@x.com")
        await client.post(
            "/api/v1/appointments",
            headers=headers,
            json={
                "title": "Rendez-vous Zorglub",
                "start_at": "2026-07-02T10:00:00Z",
                "end_at": "2026-07-02T10:30:00Z",
            },
        )
        r = await client.get("/api/v1/search?q=Zorglub", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["query"] == "Zorglub"
        assert any("Zorglub" in a["title"] for a in data["appointments"])

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "search2@x.com")
        r = await client.get("/api/v1/search?q=", headers=headers)
        assert r.status_code == 422  # min_length=1


# ── Réservation publique ───────────────────────────────────────────────────


class TestPublicBooking:
    @pytest.mark.asyncio
    async def test_full_booking_flow(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "salon@x.com")
        slug = (await client.get("/api/v1/business/me", headers=headers)).json()["slug"]

        # Infos publiques (sans auth).
        info = await client.get(f"/api/v1/public/booking/{slug}")
        assert info.status_code == 200, info.text
        assert info.json()["slug"] == slug

        # Créneaux d'un lundi futur (horaires par défaut lun-ven 9h-18h).
        day = _next_weekday().isoformat()
        slots = await client.get(f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30")
        assert slots.status_code == 200, slots.text
        available = slots.json()["slots"]
        assert len(available) > 0, "des créneaux devraient exister un lundi"
        chosen = available[0]["start_at"]

        # Réservation du premier créneau (sans auth).
        book = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Camille Martin",
                "email": "camille@client.com",
                "phone": "+33600000000",
                "start_at": chosen,
                "duration": 30,
                "notes": "Première visite",
            },
        )
        assert book.status_code == 201, book.text
        assert book.json()["status"] == "scheduled"

        # Le créneau n'est plus proposé.
        slots2 = await client.get(f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30")
        assert all(s["start_at"] != chosen for s in slots2.json()["slots"])

        # Double réservation du même créneau → conflit.
        clash = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Autre Client",
                "email": "autre@client.com",
                "start_at": chosen,
                "duration": 30,
            },
        )
        assert clash.status_code == 409, clash.text

        # Le RDV existe côté business, et le client est créé + cherchable.
        appts = (await client.get("/api/v1/appointments", headers=headers)).json()
        assert appts["total"] == 1
        assert appts["appointments"][0]["channel"] == "booking"

        found = (await client.get("/api/v1/search?q=Camille", headers=headers)).json()
        assert any(c["full_name"] == "Camille Martin" for c in found["customers"])

    @pytest.mark.asyncio
    async def test_unknown_slug_404(self, client: AsyncClient, db_tables: None) -> None:
        r = await client.get("/api/v1/public/booking/inexistant-xyz")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_past_slot_rejected(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "salon2@x.com")
        slug = (await client.get("/api/v1/business/me", headers=headers)).json()["slug"]
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Trop Tard",
                "email": "late@client.com",
                "start_at": "2020-01-01T10:00:00Z",
                "duration": 30,
            },
        )
        assert r.status_code == 400
