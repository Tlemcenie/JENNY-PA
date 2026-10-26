"""Tests e2e : agenda dashboard, pas de surréservation par coiffeur."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
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
            .values(business_hours=_OPEN_ALL, timezone="Europe/Paris")
        )
    return headers, bid


def _at(hour: int, minute: int = 0, offset: int = 3) -> str:
    day = (datetime.now(_PARIS) + timedelta(days=offset)).date()
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_PARIS)
    return local.astimezone(UTC).isoformat()


def _slot(h1: int, m1: int, h2: int, m2: int, **extra) -> dict:
    return {"title": "Coupe", "start_at": _at(h1, m1), "end_at": _at(h2, m2), **extra}


async def _new_staff(client: AsyncClient, headers: dict, name: str) -> dict:
    r = await client.post("/api/v1/staff", headers=headers, json={"display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


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


class TestCreateCapacity:
    @pytest.mark.asyncio
    async def test_auto_refused_when_only_staff_busy(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "solo-lea@x.com")
        lea = await _new_staff(client, headers, "Léa")
        r = await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30, staff_id=lea["id"]))
        assert r.status_code == 201, r.text

        # avant : 201 sans coiffeur, deux RDV pour un fauteuil
        auto = await client.post(
            _URL, headers=headers, json=_slot(10, 0, 10, 30, auto_assign_staff=True)
        )
        assert auto.status_code == 409, auto.text
        assert "coiffeur libre" in auto.json()["detail"]
        loose = await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30))
        assert loose.status_code == 409, loose.text
        assert await _count(bid) == 1

        # créneau collé : ok
        nxt = await client.post(
            _URL, headers=headers, json=_slot(10, 30, 11, 0, auto_assign_staff=True)
        )
        assert nxt.status_code == 201 and nxt.json()["staff_id"] == lea["id"]

    @pytest.mark.asyncio
    async def test_explicit_staff_over_legacy_rdv(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "legacy@x.com")
        # RDV pris avant l'arrivée des coiffeurs
        old = await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0))
        assert old.status_code == 201 and old.json()["staff_id"] is None
        lea = await _new_staff(client, headers, "Léa")

        r = await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0, staff_id=lea["id"]))
        assert r.status_code == 409, r.text

        # un 2e fauteuil : ça passe
        marc = await _new_staff(client, headers, "Marc")
        r = await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0, staff_id=lea["id"]))
        assert r.status_code == 201, r.text
        # 3 RDV pour 2 fauteuils : non
        r = await client.post(_URL, headers=headers, json=_slot(10, 30, 11, 0, staff_id=marc["id"]))
        assert r.status_code == 409, r.text
        assert await _count(bid) == 2

    @pytest.mark.asyncio
    async def test_auto_fills_chairs_then_409(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "two@x.com")
        await _new_staff(client, headers, "Léa")
        await _new_staff(client, headers, "Marc")
        body = _slot(14, 0, 15, 0, auto_assign_staff=True)
        names = []
        for _ in range(2):
            r = await client.post(_URL, headers=headers, json=body)
            assert r.status_code == 201, r.text
            names.append(r.json()["staff_name"])
        assert sorted(names) == ["Léa", "Marc"]
        third = await client.post(_URL, headers=headers, json=body)
        assert third.status_code == 409

    @pytest.mark.asyncio
    async def test_outside_hours_still_allowed(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "early@x.com")
        lea = await _new_staff(client, headers, "Léa")
        # avant ouverture : le gérant décide
        r = await client.post(_URL, headers=headers, json=_slot(8, 0, 8, 30, staff_id=lea["id"]))
        assert r.status_code == 201, r.text
        auto = await client.post(
            _URL, headers=headers, json=_slot(7, 0, 7, 30, auto_assign_staff=True)
        )
        assert auto.status_code == 201 and auto.json()["staff_id"] == lea["id"]

    @pytest.mark.asyncio
    async def test_solo_salon_overlap(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "nostaff@x.com")
        assert (
            await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30))
        ).status_code == 201
        clash = await client.post(_URL, headers=headers, json=_slot(10, 15, 10, 45))
        assert clash.status_code == 409
        assert "chevauche" in clash.json()["detail"]
        auto = await client.post(
            _URL, headers=headers, json=_slot(10, 15, 10, 45, auto_assign_staff=True)
        )
        assert auto.status_code == 409
        ok = await client.post(_URL, headers=headers, json=_slot(10, 30, 11, 0))
        assert ok.status_code == 201 and ok.json()["staff_id"] is None

    @pytest.mark.asyncio
    async def test_db_conflict_on_flush_is_409(
        self, client: AsyncClient, db_tables: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers, _ = await _auth(client, "race@x.com")
        real_flush = AsyncSession.flush

        async def _flush(self: AsyncSession, *a, **kw):
            # la contrainte Postgres saute au flush
            if any(isinstance(o, Appointment) for o in self.new):
                raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_flush(self, *a, **kw)

        monkeypatch.setattr(AsyncSession, "flush", _flush)
        r = await client.post(_URL, headers=headers, json=_slot(10, 0, 10, 30))
        assert r.status_code == 409, r.text


class TestUpdateCapacity:
    @pytest.mark.asyncio
    async def test_patch_checks_staff(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "patch@x.com")
        lea = await _new_staff(client, headers, "Léa")
        marc = await _new_staff(client, headers, "Marc")
        a1 = (
            await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0, staff_id=lea["id"]))
        ).json()
        await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0, staff_id=marc["id"]))
        a3 = (
            await client.post(_URL, headers=headers, json=_slot(14, 0, 15, 0, staff_id=lea["id"]))
        ).json()

        def _patch(aid: str, **body):
            return client.patch(f"{_URL}/{aid}", headers=headers, json=body)

        # déplacé sur Léa occupée
        r = await _patch(a3["id"], start_at=_at(10, 30), end_at=_at(11, 30))
        assert r.status_code == 409, r.text
        # sans coiffeur : plus de fauteuil
        r = await _patch(a3["id"], start_at=_at(10, 30), end_at=_at(11, 30), staff_id=None)
        assert r.status_code == 409, r.text
        # changement de coiffeur seul
        r = await _patch(a1["id"], staff_id=marc["id"])
        assert r.status_code == 409, r.text
        # titre seul : pas de contrôle
        r = await _patch(a1["id"], title="Coupe + brushing")
        assert r.status_code == 200, r.text
        # fin seule, sur soi-même : ok
        r = await _patch(a1["id"], end_at=_at(11, 15))
        assert r.status_code == 200, r.text

        # place libérée, puis réactivation refusée
        assert (await _patch(a1["id"], status="cancelled")).status_code == 200
        r = await _patch(a3["id"], start_at=_at(10, 30), end_at=_at(11, 30))
        assert r.status_code == 200, r.text
        r = await _patch(a1["id"], status="scheduled")
        assert r.status_code == 409, r.text

    @pytest.mark.asyncio
    async def test_patch_end_before_start(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "badend@x.com")
        a = (await client.post(_URL, headers=headers, json=_slot(10, 0, 11, 0))).json()
        r = await client.patch(f"{_URL}/{a['id']}", headers=headers, json={"end_at": _at(9, 0)})
        assert r.status_code == 400
