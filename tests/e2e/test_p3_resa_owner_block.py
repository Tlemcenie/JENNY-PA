"""Passe 3 résa : le blocage gérant ne bloque jamais tout le salon en douce.

Coiffeur en pause, prénom inconnu ou ambigu : Jenny le dit et ne bloque
rien. Blocage du salon : la réponse le dit clairement. SQLite réel.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff
from jenny.services.owner_assistant import _name_guess, handle_owner_message

_PARIS = ZoneInfo("Europe/Paris")
_HOURS = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


def _day() -> date:
    return (datetime.now(_PARIS) + timedelta(days=3)).date()


def _txt(day: date) -> str:
    return f"{day.day:02d}/{day.month:02d}/{day.year}"


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=_PARIS).astimezone(UTC)


async def _salon(*staff: tuple[str, bool]) -> tuple[Business, dict[str, Staff]]:
    async with async_session_factory() as s, s.begin():
        b = Business(
            id=uuid4(),
            name="Salon",
            slug=f"s-{uuid4().hex[:6]}",
            timezone="Europe/Paris",
            business_hours=_HOURS,
        )
        s.add(b)
        s.add(Prestation(business_id=b.id, name="Coupe", price_cents=3000, duration_minutes=30))
        members = {}
        for i, (name, active) in enumerate(staff):
            m = Staff(
                business_id=b.id,
                display_name=name,
                is_active=active,
                created_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            s.add(m)
            members[name] = m
    return b, members


async def _say(biz: Business, message: str) -> dict:
    async with async_session_factory() as s:
        return await handle_owner_message(s, business_id=biz.id, actor="gerant", message=message)


async def _blocks(biz: Business) -> list[Appointment]:
    async with async_session_factory() as s:
        rows = await s.execute(
            select(Appointment).where(
                Appointment.business_id == biz.id, Appointment.status == "blocked"
            )
        )
        return list(rows.scalars().all())


async def _rdv(biz: Business, start: datetime, staff: Staff | None = None) -> None:
    async with async_session_factory() as s, s.begin():
        s.add(
            Appointment(
                business_id=biz.id,
                staff_id=staff.id if staff else None,
                title="Coupe",
                channel="chat",
                start_at=start,
                end_at=start + timedelta(minutes=30),
                status="scheduled",
                created_by="test",
            )
        )


async def _book(biz: Business, day: date, time_txt: str) -> dict:
    return await BookAppointmentDBAction().execute(
        {"business_id": str(biz.id), "service": "coupe", "date": _txt(day), "time": time_txt}
    )


class TestCoiffeurFlou:
    async def test_en_pause_rien_bloque(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", False), ("Marc", True))
        out = await _say(biz, f"bloque Léa le {_txt(_day())} 14h")
        assert out["data"].get("paused") is True
        assert "Léa est en pause" in out["response"] and "je ne bloque rien" in out["response"]
        # avant : tout le salon bloqué
        assert await _blocks(biz) == []
        res = await _book(biz, _day(), "14h")
        assert res["success"] and res["staff_name"] == "Marc"

    async def test_conge_en_pause(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", False), ("Marc", True))
        out = await _say(biz, f"Léa est en congé le {_txt(_day())}")
        assert out["data"].get("paused") is True and await _blocks(biz) == []

    async def test_tout_en_pause(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", False))
        out = await _say(biz, f"bloque Léa le {_txt(_day())} 14h")
        assert out["data"].get("paused") is True and await _blocks(biz) == []

    async def test_prenom_inconnu(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", True), ("Marc", True))
        out = await _say(biz, f"bloque Jade le {_txt(_day())} 14h")
        assert out["data"].get("unknown_staff") == "Jade"
        assert "Je ne trouve pas « Jade »" in out["response"]
        assert "Léa et Marc" in out["response"]
        assert await _blocks(biz) == []
        out = await _say(biz, f"Jade est en congé le {_txt(_day())}")
        assert out["data"].get("unknown_staff") == "Jade" and await _blocks(biz) == []
        # « au salon » : pas tout le salon
        out = await _say(biz, f"Jade est en congé, pas au salon le {_txt(_day())}")
        assert out["data"].get("unknown_staff") == "Jade" and await _blocks(biz) == []

    async def test_prenom_ambigu(self, db_tables) -> None:
        biz, members = await _salon(("Marie Dupont", True), ("Marie Leroy", True))
        out = await _say(biz, f"bloque Marie le {_txt(_day())} 14h")
        assert out["data"].get("ambiguous") is True
        assert "Marie Dupont" in out["response"] and "Marie Leroy" in out["response"]
        assert await _blocks(biz) == []
        out = await _say(biz, f"bloque Marie Leroy le {_txt(_day())} 14h")
        rows = await _blocks(biz)
        assert len(rows) == 1 and rows[0].staff_id == members["Marie Leroy"].id

    async def test_deux_coiffeurs_un_par_un(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", True), ("Marc", True))
        out = await _say(biz, f"bloque Léa et Marc le {_txt(_day())} 14h")
        assert out["data"].get("several") is True
        assert "Léa puis pour Marc" in out["response"]
        assert await _blocks(biz) == []

    async def test_accent_oublie(self, db_tables) -> None:
        biz, members = await _salon(("Léa", True), ("Marc", True))
        await _say(biz, f"bloque lea le {_txt(_day())} 14h")
        rows = await _blocks(biz)
        assert len(rows) == 1 and rows[0].staff_id == members["Léa"].id


class TestBlocageSalon:
    async def test_sans_nom_dit_tout_le_salon(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", True), ("Marc", True))
        out = await _say(biz, f"bloque le {_txt(_day())} 14h")
        assert out["data"].get("salon") is True
        assert "tout le salon" in out["response"] and "Léa et Marc compris" in out["response"]
        rows = await _blocks(biz)
        assert len(rows) == 1 and rows[0].staff_id is None

    async def test_salon_explicite(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", True), ("Marc", True))
        out = await _say(biz, f"Bloque tout le salon le {_txt(_day())} 14h, Formation")
        assert out["data"].get("salon") is True
        assert len(await _blocks(biz)) == 1

    async def test_solo_inchange(self, db_tables) -> None:
        biz, _ = await _salon()
        out = await _say(biz, f"bloque le {_txt(_day())} 14h")
        assert "tu n'es pas disponible" in out["response"]
        assert len(await _blocks(biz)) == 1


class TestCapacite:
    async def test_rdv_sans_coiffeur_garde_un_fauteuil(self, db_tables) -> None:
        biz, members = await _salon(("Léa", True), ("Marc", True))
        day = _day()
        await _rdv(biz, _at(day, 14))
        await _rdv(biz, _at(day, 14), members["Marc"])
        out = await _say(biz, f"bloque Léa le {_txt(day)} 14h")
        assert out["data"].get("conflict") is True
        assert "sans coiffeur" in out["response"]
        assert await _blocks(biz) == []

    async def test_salon_deja_bloque(self, db_tables) -> None:
        biz, _ = await _salon(("Léa", True), ("Marc", True))
        await _say(biz, f"bloque tout le salon le {_txt(_day())} 14h")
        out = await _say(biz, f"bloque Léa le {_txt(_day())} 14h")
        assert out["data"].get("conflict") is True
        assert len(await _blocks(biz)) == 1


@pytest.mark.parametrize(
    ("msg", "guess"),
    [
        ("bloque Jade mardi 14h", "Jade"),
        ("Jade est malade demain", "Jade"),
        ("Bloque mardi de 14h à 16h", None),
        ("Je ne suis pas là Mardi", None),
        ("Indisponible le 12 Novembre", None),
        ("Pas dispo demain, Merci", None),
        ("bloque le RDV de 15h", None),
    ],
)
def test_name_guess(msg: str, guess: str | None) -> None:
    assert _name_guess(msg) == guess
