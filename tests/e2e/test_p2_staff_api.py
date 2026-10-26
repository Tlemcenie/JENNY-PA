"""Passe 2 staff : routes équipe, agenda (annulation, compétences), résa en ligne."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.staff import Staff, StaffSkill
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services import availability, gap_filler

_PASSWORD = "Strong#1234"
_PARIS = ZoneInfo("Europe/Paris")
_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_URL = "/api/v1/appointments"


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
    async with async_session_factory() as s, s.begin():
        await s.execute(
            update(Business)
            .where(Business.id == UUID(bid))
            .values(business_hours=_OPEN_ALL, timezone="Europe/Paris", phone="01 23 45 67 89")
        )
    return headers, bid


def _day_iso(offset: int = 3) -> str:
    return (datetime.now(_PARIS) + timedelta(days=offset)).date().isoformat()


def _at(hour: int, minute: int = 0, offset: int = 3) -> str:
    day = (datetime.now(_PARIS) + timedelta(days=offset)).date()
    return (
        datetime(day.year, day.month, day.day, hour, minute, tzinfo=_PARIS)
        .astimezone(UTC)
        .isoformat()
    )


def _slot(h1: int, m1: int, h2: int, m2: int, **extra) -> dict:
    return {"title": "Coupe", "start_at": _at(h1, m1), "end_at": _at(h2, m2), **extra}


async def _presta(client: AsyncClient, headers: dict, name: str, minutes: int) -> dict:
    r = await client.post(
        "/api/v1/prestations",
        headers=headers,
        json={"name": name, "duration_minutes": minutes, "price_cents": 4000},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _staff(client: AsyncClient, headers: dict, name: str, **extra) -> dict:
    r = await client.post("/api/v1/staff", headers=headers, json={"display_name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _slug(bid: str) -> str:
    async with async_session_factory() as s:
        return (await s.get(Business, UUID(bid))).slug


async def _count(bid: str) -> int:
    async with async_session_factory() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.business_id == UUID(bid))
            )
            or 0
        )


# ── route équipe ──


class TestStaffFlag:
    @pytest.mark.asyncio
    async def test_flag_follows_skills(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "flag@x.com")
        couleur = await _presta(client, headers, "Couleur", 60)
        lea = await _staff(client, headers, "Léa", prestation_ids=[couleur["id"]])
        zoe = await _staff(client, headers, "Zoé")
        assert lea["all_services"] is False and zoe["all_services"] is True

        # restreint sans rien coché : refusé
        r = await client.post(
            "/api/v1/staff", headers=headers, json={"display_name": "Max", "all_services": False}
        )
        assert r.status_code == 400
        r = await client.patch(
            f"/api/v1/staff/{zoe['id']}", headers=headers, json={"all_services": False}
        )
        assert r.status_code == 400

        # tout faire : liste vidée
        r = await client.patch(
            f"/api/v1/staff/{lea['id']}", headers=headers, json={"all_services": True}
        )
        assert r.status_code == 200 and r.json()["all_services"] is True
        assert r.json()["prestation_ids"] == []

        # ancien contrat : liste vide = tout
        r = await client.put(
            f"/api/v1/staff/{zoe['id']}/skills",
            headers=headers,
            json={"prestation_ids": [couleur["id"]]},
        )
        assert r.json()["all_services"] is False
        r = await client.put(
            f"/api/v1/staff/{zoe['id']}/skills", headers=headers, json={"prestation_ids": []}
        )
        assert r.json()["all_services"] is True

        lst = (await client.get("/api/v1/staff", headers=headers)).json()["staff"]
        assert all("all_services" in m for m in lst)

    @pytest.mark.asyncio
    async def test_deleted_prestation_keeps_restriction(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, _ = await _auth(client, "cascade@x.com")
        couleur = await _presta(client, headers, "Couleur", 60)
        lea = await _staff(client, headers, "Léa", prestation_ids=[couleur["id"]])
        assert (
            await client.delete(f"/api/v1/prestations/{couleur['id']}", headers=headers)
        ).status_code in (
            200,
            204,
        )
        # sqlite : on fait le CASCADE
        async with async_session_factory() as s, s.begin():
            await s.execute(delete(StaffSkill).where(StaffSkill.staff_id == UUID(lea["id"])))
        got = (await client.get(f"/api/v1/staff/{lea['id']}", headers=headers)).json()
        # toujours restreinte, pas polyvalente
        assert got["all_services"] is False and got["prestation_ids"] == []


# ── agenda : compétences et coiffeur en pause ──


class TestDashboardSkills:
    @pytest.mark.asyncio
    async def test_auto_respects_prestation(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "skills@x.com")
        coupe = await _presta(client, headers, "Coupe", 30)
        couleur = await _presta(client, headers, "Couleur", 60)
        await _staff(client, headers, "Marc", prestation_ids=[coupe["id"]])
        lea = await _staff(client, headers, "Léa", prestation_ids=[couleur["id"]])

        r = await client.post(
            _URL,
            headers=headers,
            json=_slot(10, 0, 11, 0, auto_assign_staff=True, prestation_id=couleur["id"]),
        )
        assert r.status_code == 201 and r.json()["staff_name"] == "Léa"
        # titre exact = prestation connue
        r = await client.post(
            _URL,
            headers=headers,
            json={**_slot(14, 0, 15, 0, auto_assign_staff=True), "title": "Couleur"},
        )
        assert r.status_code == 201 and r.json()["staff_name"] == "Léa"
        # titre libre : premier libre
        r = await client.post(
            _URL,
            headers=headers,
            json={**_slot(16, 0, 17, 0, auto_assign_staff=True), "title": "Couleur et conseils"},
        )
        assert r.status_code == 201 and r.json()["staff_name"] == "Marc"

        # Léa prise, Marc libre mais pas coloriste
        r = await client.post(
            _URL,
            headers=headers,
            json=_slot(10, 0, 11, 0, auto_assign_staff=True, prestation_id=couleur["id"]),
        )
        assert r.status_code == 409 and "prestation" in r.json()["detail"]
        # choix explicite : le gérant décide
        r = await client.post(
            _URL,
            headers=headers,
            json=_slot(10, 0, 11, 0, staff_id=None, prestation_id=couleur["id"]),
        )
        assert r.status_code == 201, r.text
        assert r.json()["staff_id"] is None
        assert lea["all_services"] is False

    @pytest.mark.asyncio
    async def test_foreign_prestation_refused(self, client: AsyncClient, db_tables: None) -> None:
        h1, _ = await _auth(client, "a@x.com")
        h2, _ = await _auth(client, "b@x.com")
        other = await _presta(client, h2, "Coupe", 30)
        r = await client.post(
            _URL,
            headers=h1,
            json=_slot(10, 0, 10, 30, auto_assign_staff=True, prestation_id=other["id"]),
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_paused_stylist_frees_capacity(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "pause@x.com")
        lea = await _staff(client, headers, "Léa")
        await _staff(client, headers, "Marc")
        a = (
            await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30, staff_id=lea["id"]))
        ).json()
        r = await client.patch(
            f"/api/v1/staff/{lea['id']}", headers=headers, json={"is_active": False}
        )
        assert r.status_code == 200
        # avant : 409, Léa comptait comme un fauteuil
        r = await client.post(
            _URL, headers=headers, json=_slot(10, 0, 10, 30, auto_assign_staff=True)
        )
        assert r.status_code == 201 and r.json()["staff_name"] == "Marc"
        # le RDV de Léa garde son coiffeur
        r = await client.patch(f"{_URL}/{a['id']}", headers=headers, json={"end_at": _at(10, 45)})
        assert r.status_code == 200 and r.json()["staff_id"] == lea["id"]
        # Léa contre elle-même : 409
        r = await client.post(_URL, headers=headers, json=_slot(10, 15, 10, 45, staff_id=lea["id"]))
        assert r.status_code == 409
        assert await _count(bid) == 2


# ── agenda : place libérée ──


class TestFreedSlot:
    @pytest.mark.asyncio
    async def test_cancel_and_delete_notify(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, bid = await _auth(client, "freed@x.com")
        calls: list[UUID] = []

        async def _spy(db, business_id, **kw) -> bool:
            calls.append(business_id)
            return True

        monkeypatch.setattr(gap_filler, "schedule_after_change", _spy)
        async with async_session_factory() as s, s.begin():
            s.add(WaitlistEntry(business_id=UUID(bid), service="coupe", customer_name="Inès"))
        a = (await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30))).json()
        b = (await client.post(_URL, headers=headers, json=_slot(14, 0, 14, 30))).json()

        r = await client.patch(f"{_URL}/{a['id']}", headers=headers, json={"status": "cancelled"})
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        async with async_session_factory() as s:
            entry = (
                await s.execute(select(WaitlistEntry).where(WaitlistEntry.business_id == UUID(bid)))
            ).scalar_one()
        assert entry.status == "notified"
        assert UUID(bid) in calls

        # déjà annulé : rien de plus
        n = len(calls)
        assert (
            await client.patch(f"{_URL}/{a['id']}", headers=headers, json={"status": "cancelled"})
        ).status_code == 200
        assert len(calls) == n

        assert (await client.delete(f"{_URL}/{b['id']}", headers=headers)).status_code == 200
        assert len(calls) > n

    @pytest.mark.asyncio
    async def test_hook_failure_never_blocks(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, bid = await _auth(client, "boom@x.com")

        async def _boom(*a, **kw) -> bool:
            raise RuntimeError("relances en panne")

        monkeypatch.setattr(gap_filler, "schedule_after_change", _boom)
        a = (await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30))).json()
        r = await client.patch(f"{_URL}/{a['id']}", headers=headers, json={"status": "cancelled"})
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        b = (await client.post(_URL, headers=headers, json=_slot(11, 0, 11, 30))).json()
        assert (await client.delete(f"{_URL}/{b['id']}", headers=headers)).status_code == 200
        assert await _count(bid) == 1

    @pytest.mark.asyncio
    async def test_past_rdv_no_hook(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, _ = await _auth(client, "past@x.com")
        calls: list[UUID] = []
        monkeypatch.setattr(
            gap_filler, "schedule_after_change", lambda db, bid, **kw: calls.append(bid)
        )
        past = {"title": "Coupe", "start_at": _at(10, offset=-2), "end_at": _at(11, offset=-2)}
        a = (await client.post(_URL, headers=headers, json=past)).json()
        assert (await client.delete(f"{_URL}/{a['id']}", headers=headers)).status_code == 200
        assert calls == []


# ── réservation en ligne ──


class TestPublicBooking:
    @pytest.mark.asyncio
    async def test_info_exposes_staff_and_catalog(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "info@x.com")
        couleur = await _presta(client, headers, "Couleur", 60)
        await _staff(client, headers, "Léa", prestation_ids=[couleur["id"]])
        await _staff(client, headers, "Zoé")
        info = (await client.get(f"/api/v1/public/booking/{await _slug(bid)}")).json()
        assert info["phone"] == "01 23 45 67 89"
        by_name = {m["display_name"]: m for m in info["staff"]}
        assert by_name["Léa"]["prestation_ids"] == [couleur["id"]]
        assert by_name["Zoé"]["prestation_ids"] is None
        assert [p["name"] for p in info["prestations"]] == ["Couleur"]
        assert info["prestations"][0]["duration_minutes"] == 60

    @pytest.mark.asyncio
    async def test_slots_and_book_follow_prestation(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "online@x.com")
        coupe = await _presta(client, headers, "Coupe", 30)
        couleur = await _presta(client, headers, "Couleur", 60)
        marc = await _staff(client, headers, "Marc", prestation_ids=[coupe["id"]])
        lea = await _staff(client, headers, "Léa", prestation_ids=[couleur["id"]])
        slug = await _slug(bid)
        day = _day_iso()

        r = await client.get(
            f"/api/v1/public/booking/{slug}/slots",
            params={"date": day, "prestation_id": couleur["id"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["duration_minutes"] == 60
        assert body["slots"] and all(s["staff_ids"] == [lea["id"]] for s in body["slots"])

        # coiffeur incompétent : rien
        r = await client.get(
            f"/api/v1/public/booking/{slug}/slots",
            params={"date": day, "prestation_id": couleur["id"], "staff_id": marc["id"]},
        )
        assert r.json()["slots"] == []

        start = body["slots"][0]["start_at"]
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Sophie Martin",
                "email": "sophie@x.com",
                "start_at": start,
                "prestation_id": couleur["id"],
            },
        )
        assert r.status_code == 201, r.text
        conf = r.json()
        assert conf["staff_name"] == "Léa" and conf["prestation_name"] == "Couleur"
        got_start = datetime.fromisoformat(conf["start_at"].replace("Z", "+00:00"))
        got_end = datetime.fromisoformat(conf["end_at"].replace("Z", "+00:00"))
        assert got_end - got_start == timedelta(minutes=60)
        async with async_session_factory() as s:
            appt = await s.get(Appointment, UUID(conf["id"]))
        assert appt.title == "Couleur"

        # Marc choisi pour une couleur : refusé
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Ana",
                "email": "ana@x.com",
                "start_at": body["slots"][-1]["start_at"],
                "prestation_id": couleur["id"],
                "staff_id": marc["id"],
            },
        )
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_booking_pushes_live_event(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, bid = await _auth(client, "live@x.com")
        from jenny.api.routes import public_booking

        seen: list[tuple] = []
        monkeypatch.setattr(
            public_booking, "publish_notification_event", lambda b, **kw: seen.append((b, kw))
        )
        r = await client.post(
            f"/api/v1/public/booking/{await _slug(bid)}/book",
            json={"full_name": "Sophie", "email": "live-s@x.com", "start_at": _at(10)},
        )
        assert r.status_code == 201, r.text
        # agenda rafraîchi en direct
        assert seen and seen[0][0] == UUID(bid) and seen[0][1]["kind"] == "booking"

    @pytest.mark.asyncio
    async def test_unknown_prestation_400(self, client: AsyncClient, db_tables: None) -> None:
        _, bid = await _auth(client, "p1@x.com")
        h2, _ = await _auth(client, "p2@x.com")
        other = await _presta(client, h2, "Coupe", 30)
        slug = await _slug(bid)
        r = await client.get(
            f"/api/v1/public/booking/{slug}/slots",
            params={"date": _day_iso(), "prestation_id": other["id"]},
        )
        assert r.status_code == 400
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "X",
                "email": "x@x.com",
                "start_at": _at(10),
                "prestation_id": other["id"],
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_race_retries_other_stylist(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, bid = await _auth(client, "race@x.com")
        await _staff(client, headers, "Léa")
        await _staff(client, headers, "Marc")
        slug = await _slug(bid)
        real_flush = AsyncSession.flush
        real_pick = availability.find_free_staff
        calls = {"flush": 0, "pick": 0}

        async def _flush(self: AsyncSession, *a, **kw):
            if any(isinstance(o, Appointment) for o in self.new):
                calls["flush"] += 1
                if calls["flush"] == 1:
                    raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_flush(self, *a, **kw)

        async def _pick(*a, **kw):
            calls["pick"] += 1
            return await real_pick(*a, **kw)

        monkeypatch.setattr(AsyncSession, "flush", _flush)
        from jenny.api.routes import public_booking

        monkeypatch.setattr(public_booking, "find_free_staff", _pick)
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={"full_name": "Sophie", "email": "s@x.com", "start_at": _at(10)},
        )
        # avant : 500 (flush hors du try)
        assert r.status_code == 201, r.text
        assert calls["pick"] == 2
        assert await _count(bid) == 1

    @pytest.mark.asyncio
    async def test_race_with_chosen_stylist_is_409(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, bid = await _auth(client, "race2@x.com")
        lea = await _staff(client, headers, "Léa")
        slug = await _slug(bid)
        real_flush = AsyncSession.flush

        async def _flush(self: AsyncSession, *a, **kw):
            if any(isinstance(o, Appointment) for o in self.new):
                raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_flush(self, *a, **kw)

        monkeypatch.setattr(AsyncSession, "flush", _flush)
        r = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={
                "full_name": "Sophie",
                "email": "s@x.com",
                "start_at": _at(10),
                "staff_id": lea["id"],
            },
        )
        assert r.status_code == 409
        monkeypatch.undo()
        assert await _count(bid) == 0
        async with async_session_factory() as s:
            assert await s.get(Staff, UUID(lea["id"])) is not None
