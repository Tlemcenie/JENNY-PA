"""Tests e2e : routes équipe, agenda par coiffeur et résa en ligne multi-fauteuils."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business

_PASSWORD = "Strong#1234"
_PARIS = ZoneInfo("Europe/Paris")
_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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
            .values(business_hours=_OPEN_ALL, timezone="Europe/Paris")
        )
    return headers, bid


def _day_iso(offset: int = 3) -> str:
    return (datetime.now(_PARIS) + timedelta(days=offset)).date().isoformat()


def _at_iso(day_iso: str, hour: int) -> str:
    y, m, d = (int(x) for x in day_iso.split("-"))
    return datetime(y, m, d, hour, tzinfo=_PARIS).astimezone(UTC).isoformat()


async def _new_staff(client: AsyncClient, headers: dict, name: str, **extra) -> dict:
    r = await client.post("/api/v1/staff", headers=headers, json={"display_name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


class TestStaffCrud:
    @pytest.mark.asyncio
    async def test_create_list_update(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "team@x.com")
        presta = (
            await client.post(
                "/api/v1/prestations",
                headers=headers,
                json={"name": "Couleur", "duration_minutes": 60, "price_cents": 6000},
            )
        ).json()
        lea = await _new_staff(client, headers, "Léa", prestation_ids=[presta["id"]])
        marc = await _new_staff(client, headers, "Marc", color="#123ABC")
        assert lea["color"] and lea["color"] != marc["color"]  # palette auto
        assert marc["color"] == "#123abc"
        assert lea["prestation_ids"] == [presta["id"]]

        lst = (await client.get("/api/v1/staff", headers=headers)).json()
        assert lst["total"] == 2 and [m["display_name"] for m in lst["staff"]] == ["Léa", "Marc"]

        hours = {"mon": None, "tue": ["10:00", "18:00"]}
        r = await client.patch(
            f"/api/v1/staff/{marc['id']}", headers=headers, json={"working_hours": hours}
        )
        assert r.status_code == 200, r.text
        assert r.json()["working_hours"] == hours
        # null = horaires du salon
        r = await client.patch(
            f"/api/v1/staff/{marc['id']}", headers=headers, json={"working_hours": None}
        )
        assert r.json()["working_hours"] is None

        r = await client.put(f"/api/v1/staff/{lea['id']}/skills", headers=headers, json={"prestation_ids": []})
        assert r.status_code == 200 and r.json()["prestation_ids"] == []

    @pytest.mark.asyncio
    async def test_validation(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "valid@x.com")
        bad_hours = await client.post(
            "/api/v1/staff",
            headers=headers,
            json={"display_name": "X", "working_hours": {"tue": ["18:00", "09:00"]}},
        )
        assert bad_hours.status_code == 422
        bad_day = await client.post(
            "/api/v1/staff", headers=headers, json={"display_name": "X", "working_hours": {"lundi": None}}
        )
        assert bad_day.status_code == 422
        bad_color = await client.post(
            "/api/v1/staff", headers=headers, json={"display_name": "X", "color": "rouge"}
        )
        assert bad_color.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_soft_when_rdv(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "del@x.com")
        free = await _new_staff(client, headers, "Libre")
        busy = await _new_staff(client, headers, "Occupé")
        start = datetime.now(UTC) + timedelta(days=2)
        async with async_session_factory() as s, s.begin():
            s.add(
                Appointment(
                    business_id=UUID(bid), staff_id=UUID(busy["id"]), title="Coupe",
                    start_at=start, end_at=start + timedelta(minutes=30), status="scheduled",
                )
            )
        r1 = await client.delete(f"/api/v1/staff/{free['id']}", headers=headers)
        assert r1.json()["status"] == "deleted"
        r2 = await client.delete(f"/api/v1/staff/{busy['id']}", headers=headers)
        assert r2.json()["status"] == "deactivated"
        lst = (await client.get("/api/v1/staff", headers=headers)).json()["staff"]
        assert [(m["display_name"], m["is_active"], m["upcoming_count"]) for m in lst] == [
            ("Occupé", False, 1)
        ]


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_other_salon_cannot_touch(self, client: AsyncClient, db_tables: None) -> None:
        h1, _ = await _auth(client, "one@x.com")
        h2, _ = await _auth(client, "two@x.com")
        lea = await _new_staff(client, h1, "Léa")
        assert (await client.get("/api/v1/staff", headers=h2)).json()["total"] == 0
        assert (await client.get(f"/api/v1/staff/{lea['id']}", headers=h2)).status_code == 404
        r = await client.patch(f"/api/v1/staff/{lea['id']}", headers=h2, json={"display_name": "Pirate"})
        assert r.status_code == 404
        assert (await client.delete(f"/api/v1/staff/{lea['id']}", headers=h2)).status_code == 404

        # compétence avec la prestation d'un autre salon
        other = (
            await client.post("/api/v1/prestations", headers=h2, json={"name": "Coupe"})
        ).json()
        r = await client.put(
            f"/api/v1/staff/{lea['id']}/skills", headers=h1, json={"prestation_ids": [other["id"]]}
        )
        assert r.status_code == 400

        # RDV posé sur le coiffeur d'un autre salon
        day = _day_iso()
        r = await client.post(
            "/api/v1/appointments",
            headers=h2,
            json={
                "title": "Coupe",
                "start_at": _at_iso(day, 10),
                "end_at": _at_iso(day, 11),
                "staff_id": lea["id"],
            },
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient, db_tables: None) -> None:
        assert (await client.get("/api/v1/staff")).status_code == 401


class TestCalendarStaff:
    @pytest.mark.asyncio
    async def test_create_update_list_with_staff(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "cal@x.com")
        lea = await _new_staff(client, headers, "Léa")
        marc = await _new_staff(client, headers, "Marc")
        day = _day_iso()
        body = {"title": "Coupe", "start_at": _at_iso(day, 10), "end_at": _at_iso(day, 11)}

        manual = await client.post("/api/v1/appointments", headers=headers, json=body)
        assert manual.status_code == 201 and manual.json()["staff_id"] is None
        auto = await client.post(
            "/api/v1/appointments", headers=headers, json={**body, "auto_assign_staff": True}
        )
        assert auto.json()["staff_name"] == "Léa" and auto.json()["staff_color"] == lea["color"]

        r = await client.patch(
            f"/api/v1/appointments/{manual.json()['id']}", headers=headers, json={"staff_id": marc["id"]}
        )
        assert r.status_code == 200 and r.json()["staff_name"] == "Marc"

        lst = (await client.get("/api/v1/appointments", headers=headers)).json()
        assert sorted(a["staff_name"] for a in lst["appointments"]) == ["Léa", "Marc"]
        only = (
            await client.get(f"/api/v1/appointments?staff_id={marc['id']}", headers=headers)
        ).json()
        assert only["total"] == 1 and only["appointments"][0]["staff_id"] == marc["id"]

        # retire le coiffeur
        r = await client.patch(
            f"/api/v1/appointments/{manual.json()['id']}", headers=headers, json={"staff_id": None}
        )
        assert r.json()["staff_id"] is None

        ics = await client.get("/api/v1/appointments/export.ics", headers=headers)
        assert "Coiffeur : Léa" in ics.text

    @pytest.mark.asyncio
    async def test_occupancy(self, client: AsyncClient, db_tables: None) -> None:
        headers, bid = await _auth(client, "occ@x.com")
        lea = await _new_staff(client, headers, "Léa")
        await _new_staff(client, headers, "Marc")
        day = _day_iso(1)
        await client.post(
            "/api/v1/appointments",
            headers=headers,
            json={
                "title": "Couleur",
                "start_at": _at_iso(day, 10),
                "end_at": _at_iso(day, 12),
                "staff_id": lea["id"],
            },
        )
        r = await client.get("/api/v1/staff/occupancy?days=3", headers=headers)
        assert r.status_code == 200, r.text
        by_name = {m["display_name"]: m for m in r.json()["staff"]}
        assert by_name["Léa"]["booked_minutes"] == 120
        assert by_name["Marc"]["booked_minutes"] == 0
        assert by_name["Léa"]["available_minutes"] >= 600
        assert 0 < by_name["Léa"]["fill_rate"] < 1


class TestPublicBookingStaff:
    @pytest.mark.asyncio
    async def test_two_chairs_online(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "public@x.com")
        slug = (await client.get("/api/v1/business/me", headers=headers)).json()["slug"]
        lea = await _new_staff(client, headers, "Léa")
        marc = await _new_staff(client, headers, "Marc")

        info = (await client.get(f"/api/v1/public/booking/{slug}")).json()
        assert [m["display_name"] for m in info["staff"]] == ["Léa", "Marc"]

        day = _day_iso()
        slots = (
            await client.get(f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30")
        ).json()["slots"]
        assert len(slots[0]["staff_ids"]) == 2
        chosen = next(s["start_at"] for s in slots if s["label"] == "10:00")

        def _body(email: str, **extra) -> dict:
            return {"full_name": "Client", "email": email, "start_at": chosen, "duration": 30, **extra}

        b1 = await client.post(f"/api/v1/public/booking/{slug}/book", json=_body("a@c.com"))
        b2 = await client.post(f"/api/v1/public/booking/{slug}/book", json=_body("b@c.com"))
        assert b1.status_code == 201 and b2.status_code == 201, (b1.text, b2.text)
        assert {b1.json()["staff_name"], b2.json()["staff_name"]} == {"Léa", "Marc"}
        assert "avec" in b1.json()["message"]
        b3 = await client.post(f"/api/v1/public/booking/{slug}/book", json=_body("c@c.com"))
        assert b3.status_code == 409

        after = (
            await client.get(f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30")
        ).json()["slots"]
        assert all(s["label"] != "10:00" for s in after)

        # choix explicite du coiffeur
        at11 = next(s["start_at"] for s in after if s["label"] == "11:00")
        pick = await client.post(
            f"/api/v1/public/booking/{slug}/book",
            json={**_body("d@c.com"), "start_at": at11, "staff_id": marc["id"]},
        )
        assert pick.status_code == 201 and pick.json()["staff_id"] == marc["id"]
        only_lea = (
            await client.get(
                f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30&staff_id={lea['id']}"
            )
        ).json()["slots"]
        assert any(s["label"] == "11:00" for s in only_lea)
        assert all(s["staff_ids"] == [lea["id"]] for s in only_lea)

    @pytest.mark.asyncio
    async def test_unknown_staff_rejected(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "public2@x.com")
        slug = (await client.get("/api/v1/business/me", headers=headers)).json()["slug"]
        await _new_staff(client, headers, "Léa")
        day = _day_iso()
        r = await client.get(
            f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30&staff_id={uuid4()}"
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_solo_salon_info_has_no_staff(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "solo@x.com")
        slug = (await client.get("/api/v1/business/me", headers=headers)).json()["slug"]
        info = (await client.get(f"/api/v1/public/booking/{slug}")).json()
        assert info["staff"] == []
        day = _day_iso()
        slots = (
            await client.get(f"/api/v1/public/booking/{slug}/slots?date={day}&duration=30")
        ).json()["slots"]
        assert slots and all(s["staff_ids"] == [] for s in slots)
        # grille historique : pas = durée
        first, second = (datetime.fromisoformat(s["start_at"]) for s in slots[:2])
        assert second - first == timedelta(minutes=30)
