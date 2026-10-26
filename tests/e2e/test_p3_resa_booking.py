"""Passe 3 résa : la réservation en ligne garde la vraie durée.

Avant, une prestation de 6 h était coupée à 4 h : le coiffeur était
reproposé pendant qu'il travaillait encore. SQLite réel.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.business_closure import BusinessClosure
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff
from jenny.services.availability import MAX_SERVICE_MINUTES

_PARIS = ZoneInfo("Europe/Paris")
_HOURS = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_API = "/api/v1/public/booking"


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
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


def _day() -> date:
    return (datetime.now(_PARIS) + timedelta(days=3)).date()


def _at(hour: int, minute: int = 0) -> str:
    d = _day()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=_PARIS).astimezone(UTC).isoformat()


def _dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def _salon(*, staff: tuple[str, ...] = (), prestas: dict[str, int]) -> tuple[Business, dict]:
    async with async_session_factory() as s, s.begin():
        b = Business(
            id=uuid4(),
            name="Salon Zoé",
            slug=f"s-{uuid4().hex[:6]}",
            timezone="Europe/Paris",
            business_hours=_HOURS,
        )
        s.add(b)
        ids = {}
        for name, minutes in prestas.items():
            p = Prestation(
                id=uuid4(), business_id=b.id, name=name, price_cents=5000, duration_minutes=minutes
            )
            s.add(p)
            ids[name] = str(p.id)
        for i, name in enumerate(staff):
            s.add(
                Staff(
                    business_id=b.id,
                    display_name=name,
                    created_at=datetime.now(UTC) + timedelta(seconds=i),
                )
            )
    return b, ids


def _client(n: int, start: str, **extra) -> dict:
    return {"full_name": f"Cliente {n}", "email": f"c{n}@x.com", "start_at": start, **extra}


class TestPrestationLongue:
    async def test_un_coiffeur_jamais_surreserve(self, db_tables, client) -> None:
        biz, p = await _salon(staff=("Léa",), prestas={"Extensions": 360, "Coupe": 30})
        info = (await client.get(f"{_API}/{biz.slug}")).json()
        by_name = {x["name"]: x for x in info["prestations"]}
        # avant : 240
        assert by_name["Extensions"]["duration_minutes"] == 360

        # le front envoie aussi duration
        r = await client.get(
            f"{_API}/{biz.slug}/slots",
            params={"date": _day().isoformat(), "duration": 360, "prestation_id": p["Extensions"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["duration_minutes"] == 360
        r = await client.post(
            f"{_API}/{biz.slug}/book",
            json=_client(1, _at(9), duration=360, prestation_id=p["Extensions"]),
        )
        assert r.status_code == 201, r.text
        conf = r.json()
        assert _dt(conf["end_at"]) - _dt(conf["start_at"]) == timedelta(minutes=360)

        # 13h : Léa travaille encore
        slots = (
            await client.get(
                f"{_API}/{biz.slug}/slots",
                params={"date": _day().isoformat(), "prestation_id": p["Coupe"]},
            )
        ).json()["slots"]
        starts = {_dt(s["start_at"]) for s in slots}
        assert _dt(_at(13)) not in starts and _dt(_at(14, 45)) not in starts
        assert _dt(_at(15)) in starts
        r = await client.post(
            f"{_API}/{biz.slug}/book", json=_client(2, _at(13), prestation_id=p["Coupe"])
        )
        assert r.status_code == 409

    async def test_salon_solo(self, db_tables, client) -> None:
        biz, p = await _salon(prestas={"Extensions": 360, "Coupe": 30})
        r = await client.post(
            f"{_API}/{biz.slug}/book",
            json=_client(1, _at(9), duration=360, prestation_id=p["Extensions"]),
        )
        assert r.status_code == 201, r.text
        r = await client.post(
            f"{_API}/{biz.slug}/book", json=_client(2, _at(13), prestation_id=p["Coupe"])
        )
        assert r.status_code == 409
        async with async_session_factory() as s:
            appt = (await s.execute(select(Appointment))).scalar_one()
        end = appt.end_at if appt.end_at.tzinfo else appt.end_at.replace(tzinfo=UTC)
        assert end == _dt(_at(15))

    async def test_trop_longue_refusee(self, db_tables, client) -> None:
        biz, p = await _salon(staff=("Léa",), prestas={"Journée": MAX_SERVICE_MINUTES + 60})
        r = await client.get(
            f"{_API}/{biz.slug}/slots",
            params={"date": _day().isoformat(), "prestation_id": p["Journée"]},
        )
        assert r.status_code == 400
        r = await client.post(
            f"{_API}/{biz.slug}/book", json=_client(1, _at(9), prestation_id=p["Journée"])
        )
        # jamais coupée en silence
        assert r.status_code == 400
        async with async_session_factory() as s:
            assert (await s.execute(select(Appointment))).first() is None

    async def test_duree_libre_bornee(self, db_tables, client) -> None:
        biz, _ = await _salon(prestas={})
        day = _day().isoformat()
        assert (
            await client.get(f"{_API}/{biz.slug}/slots", params={"date": day, "duration": 240})
        ).status_code == 200
        assert (
            await client.get(f"{_API}/{biz.slug}/slots", params={"date": day, "duration": 300})
        ).status_code == 400
        r = await client.post(f"{_API}/{biz.slug}/book", json=_client(1, _at(9), duration=300))
        assert r.status_code == 400


class TestSoloHoraires:
    async def test_hors_horaires_refuse(self, db_tables, client) -> None:
        biz, _ = await _salon(prestas={})
        r = await client.post(f"{_API}/{biz.slug}/book", json=_client(1, _at(22)))
        assert r.status_code == 400
        r = await client.post(f"{_API}/{biz.slug}/book", json=_client(2, _at(18, 45)))
        # finit après 19h
        assert r.status_code == 400
        r = await client.post(f"{_API}/{biz.slug}/book", json=_client(3, _at(18, 30)))
        assert r.status_code == 201, r.text

    async def test_jour_ferme_refuse(self, db_tables, client) -> None:
        biz, _ = await _salon(prestas={})
        async with async_session_factory() as s, s.begin():
            s.add(BusinessClosure(business_id=biz.id, start_date=_day(), end_date=_day()))
        r = await client.post(f"{_API}/{biz.slug}/book", json=_client(1, _at(10)))
        assert r.status_code == 400


class TestChatMemeDuree:
    async def test_duree_nulle_vaut_trente(self, db_tables) -> None:
        biz, _ = await _salon(prestas={"Frange": 0, "Extensions": 360})
        d = _day()
        res = await BookAppointmentDBAction().execute(
            {
                "business_id": str(biz.id),
                "service": "frange",
                "date": f"{d.day:02d}/{d.month:02d}/{d.year}",
                "time": "10h",
            }
        )
        assert res["success"], res
        # avant : RDV de 0 min
        assert res["duration_minutes"] == 30
        res = await BookAppointmentDBAction().execute(
            {
                "business_id": str(biz.id),
                "service": "extensions",
                "date": f"{d.day:02d}/{d.month:02d}/{d.year}",
                "time": "11h",
            }
        )
        assert res["success"], res
        assert res["duration_minutes"] == 360
        async with async_session_factory() as s:
            appt = await s.get(Appointment, UUID(res["appointment_id"]))
        assert appt.end_at - appt.start_at == timedelta(minutes=360)
