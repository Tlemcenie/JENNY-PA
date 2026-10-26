"""Passe 2 staff : coiffeur en pause, drapeau « sait tout faire », blocage nommé."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff, StaffSkill
from jenny.services import availability
from jenny.services.availability import (
    StaffPool,
    find_free_staff,
    free_slots_with_staff,
    load_staff_pool,
    staff_in_text,
    staff_is_busy,
)
from jenny.services.owner_assistant import handle_owner_message

_PARIS = ZoneInfo("Europe/Paris")
_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


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


def _day(offset: int = 3) -> date:
    return (datetime.now(_PARIS) + timedelta(days=offset)).date()


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_PARIS).astimezone(UTC)


def _date_txt(day: date) -> str:
    return f"{day.day:02d}/{day.month:02d}/{day.year}"


async def _seed(staff: tuple[str, ...]) -> tuple[Business, dict[str, Staff], dict[str, Prestation]]:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(),
            name="Salon",
            slug=f"s-{uuid4().hex[:6]}",
            timezone="Europe/Paris",
            business_hours=_OPEN_ALL,
        )
        s.add(biz)
        prestas = {
            "Coupe": Prestation(
                business_id=biz.id, name="Coupe", price_cents=3000, duration_minutes=30
            ),
            "Couleur": Prestation(
                business_id=biz.id, name="Couleur", price_cents=6000, duration_minutes=60
            ),
        }
        for p in prestas.values():
            s.add(p)
        members: dict[str, Staff] = {}
        for i, name in enumerate(staff):
            m = Staff(
                business_id=biz.id,
                display_name=name,
                created_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            s.add(m)
            members[name] = m
    return biz, members, prestas


async def _add_appt(
    biz: Business,
    start: datetime,
    minutes: int = 30,
    *,
    staff: Staff | None = None,
    status: str = "scheduled",
) -> Appointment:
    async with async_session_factory() as s, s.begin():
        appt = Appointment(
            business_id=biz.id,
            staff_id=staff.id if staff else None,
            title="Coupe",
            channel="chat",
            start_at=start,
            end_at=start + timedelta(minutes=minutes),
            status=status,
            created_by="test",
        )
        s.add(appt)
    return appt


async def _pause(member: Staff) -> None:
    async with async_session_factory() as s, s.begin():
        (await s.get(Staff, member.id)).is_active = False


async def _book(biz: Business, service: str, day: date, time_txt: str, **extra) -> dict:
    params = {
        "business_id": str(biz.id),
        "service": service,
        "date": _date_txt(day),
        "time": time_txt,
    }
    params.update(extra)
    return await BookAppointmentDBAction().execute(params)


async def _appts(biz: Business) -> list[Appointment]:
    async with async_session_factory() as s:
        return list(
            (
                await s.execute(
                    select(Appointment)
                    .where(Appointment.business_id == biz.id)
                    .order_by(Appointment.created_at.asc())
                )
            )
            .scalars()
            .all()
        )


# ── coiffeur en pause ──


class TestPausedStylist:
    async def test_paused_rdv_does_not_block_others(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        await _pause(members["Léa"])
        async with async_session_factory() as s:
            pairs = dict(await free_slots_with_staff(s, biz.id, day, 30))
        # avant : 10h disparaissait
        assert [m.display_name for m in pairs[_at(day, 10)]] == ["Marc"]
        res = await _book(biz, "coupe", day, "10h")
        assert res["success"], res
        assert res["staff_name"] == "Marc"

    async def test_unassigned_still_takes_a_chair(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        await _add_appt(biz, _at(day, 10))  # sans coiffeur
        await _pause(members["Léa"])
        async with async_session_factory() as s:
            pick = await find_free_staff(s, biz.id, _at(day, 10), _at(day, 10, 30))
        # Marc seul, fauteuil anonyme pris
        assert pick.free is False and pick.has_staff is True

    async def test_paused_block_ignored(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 12), 60, staff=members["Léa"], status="blocked")
        await _pause(members["Léa"])
        res = await _book(biz, "coupe", day, "12h")
        assert res["success"] and res["staff_name"] == "Marc"

    async def test_staff_is_busy_is_per_stylist(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        appt = await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        async with async_session_factory() as s:
            lea = members["Léa"].id
            assert await staff_is_busy(s, biz.id, lea, _at(day, 10, 15), _at(day, 10, 45))
            assert not await staff_is_busy(
                s, biz.id, members["Marc"].id, _at(day, 10), _at(day, 11)
            )
            # soi-même exclu
            assert not await staff_is_busy(
                s, biz.id, lea, _at(day, 10), _at(day, 10, 30), exclude_appointment_id=appt.id
            )
            # bout à bout : libre
            assert not await staff_is_busy(s, biz.id, lea, _at(day, 10, 30), _at(day, 11))


# ── drapeau sait tout faire ──


class TestAllServicesFlag:
    def test_can_do_rules(self) -> None:
        coupe, couleur = uuid4(), uuid4()
        open_m = Staff(id=uuid4(), display_name="Zoé", all_services=True)
        strict = Staff(id=uuid4(), display_name="Léa", all_services=False)
        skilled = Staff(id=uuid4(), display_name="Marc", all_services=False)
        pool = StaffPool(members=[open_m, strict, skilled], skills={skilled.id: {coupe}})
        assert pool.can_do(open_m.id, [couleur])
        # rien coché, restreint : rien
        assert not pool.can_do(strict.id, [couleur])
        assert pool.can_do(skilled.id, [coupe]) and not pool.can_do(skilled.id, [couleur])
        # prestation inconnue : tout le monde
        assert pool.can_do(strict.id, []) and pool.can_do(strict.id, None)

    async def test_last_skill_deleted_keeps_restriction(self, db_tables) -> None:
        biz, members, prestas = await _seed(("Léa", "Marc"))
        async with async_session_factory() as s, s.begin():
            lea = await s.get(Staff, members["Léa"].id)
            lea.all_services = False
            s.add(StaffSkill(staff_id=lea.id, prestation_id=prestas["Couleur"].id))
            marc = await s.get(Staff, members["Marc"].id)
            marc.all_services = False
            s.add(StaffSkill(staff_id=marc.id, prestation_id=prestas["Coupe"].id))
        # effet du CASCADE : plus de ligne
        async with async_session_factory() as s, s.begin():
            await s.execute(delete(StaffSkill).where(StaffSkill.staff_id == members["Léa"].id))
        res = await _book(biz, "couleur", _day(), "10h")
        # avant : Léa redevenait polyvalente
        assert res["success"] is False and res.get("conflict") is True
        assert await _appts(biz) == []
        # coupe : Marc, jamais Léa
        coupe = await _book(biz, "coupe", _day(), "10h")
        assert coupe["success"] and coupe["staff_name"] == "Marc"

    async def test_default_flag_keeps_old_rule(self, db_tables) -> None:
        biz, _, _ = await _seed(("Zoé",))
        async with async_session_factory() as s:
            pool = await load_staff_pool(s, biz.id)
        assert pool.members[0].all_services is True
        res = await _book(biz, "couleur", _day(), "10h")
        assert res["success"] and res["staff_name"] == "Zoé"


# ── course entre deux résas ──


class TestChatRace:
    async def test_auto_retries_once(self, db_tables, monkeypatch: pytest.MonkeyPatch) -> None:
        biz, _, _ = await _seed(("Léa", "Marc"))
        real_flush = AsyncSession.flush
        calls = {"flush": 0, "pick": 0}

        async def _flush(self: AsyncSession, *a, **kw):
            if any(isinstance(o, Appointment) for o in self.new):
                calls["flush"] += 1
                if calls["flush"] == 1:
                    # la contrainte saute une fois
                    raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_flush(self, *a, **kw)

        real_pick = availability.find_free_staff

        async def _pick(*a, **kw):
            calls["pick"] += 1
            return await real_pick(*a, **kw)

        monkeypatch.setattr(AsyncSession, "flush", _flush)
        monkeypatch.setattr(availability, "find_free_staff", _pick)
        res = await _book(biz, "coupe", _day(), "10h")
        assert res["success"], res
        assert calls["pick"] == 2
        assert len(await _appts(biz)) == 1

    async def test_requested_stylist_no_retry(
        self, db_tables, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        biz, _, _ = await _seed(("Léa", "Marc"))
        real_flush = AsyncSession.flush

        async def _flush(self: AsyncSession, *a, **kw):
            if any(isinstance(o, Appointment) for o in self.new):
                raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_flush(self, *a, **kw)

        monkeypatch.setattr(AsyncSession, "flush", _flush)
        res = await _book(biz, "coupe", _day(), "10h", staff="léa")
        assert res["success"] is False and res.get("conflict") is True


# ── blocage par le gérant ──


class TestOwnerBlock:
    def test_staff_in_text(self) -> None:
        lea = Staff(id=uuid4(), display_name="Léa Martin")
        marc = Staff(id=uuid4(), display_name="Marc")
        pool = StaffPool(members=[lea, marc])
        assert staff_in_text(pool, "bloque lea mardi 14h") is lea
        assert staff_in_text(pool, "Marc n'est pas dispo jeudi") is marc
        assert staff_in_text(pool, "bloque mardi 14h") is None
        # pas de faux positif dans un mot
        assert staff_in_text(pool, "bloque le marché mardi") is None

    async def test_named_block_only_blocks_him(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        async with async_session_factory() as s:
            out = await handle_owner_message(
                s, business_id=biz.id, actor="gerant", message=f"bloque Léa le {_date_txt(day)} 14h"
            )
        assert out["action"] == "block_slot" and "Léa" in out["response"]
        rows = await _appts(biz)
        assert len(rows) == 1 and rows[0].status == "blocked"
        assert rows[0].staff_id == members["Léa"].id
        res = await _book(biz, "coupe", day, "14h")
        assert res["success"] and res["staff_name"] == "Marc"

    async def test_unnamed_block_is_salon_wide(self, db_tables) -> None:
        biz, _, _ = await _seed(("Léa", "Marc"))
        day = _day()
        async with async_session_factory() as s:
            await handle_owner_message(
                s, business_id=biz.id, actor="gerant", message=f"bloque le {_date_txt(day)} 14h"
            )
        rows = await _appts(biz)
        assert len(rows) == 1 and rows[0].staff_id is None
        res = await _book(biz, "coupe", day, "14h")
        assert res["success"] is False

    async def test_named_block_over_rdv_refused(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 14), staff=members["Léa"])
        async with async_session_factory() as s:
            out = await handle_owner_message(
                s, business_id=biz.id, actor="gerant", message=f"bloque Léa le {_date_txt(day)} 14h"
            )
        assert out["data"].get("conflict") is True
        assert len(await _appts(biz)) == 1

    async def test_db_conflict_is_friendly(
        self, db_tables, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        biz, _, _ = await _seed(())
        real_commit = AsyncSession.commit

        async def _commit(self: AsyncSession, *a, **kw):
            if any(isinstance(o, Appointment) for o in self.new):
                raise IntegrityError("INSERT", {}, Exception("appointments_no_overlap"))
            return await real_commit(self, *a, **kw)

        monkeypatch.setattr(AsyncSession, "commit", _commit)
        async with async_session_factory() as s:
            out = await handle_owner_message(
                s, business_id=biz.id, actor="gerant", message=f"bloque le {_date_txt(_day())} 14h"
            )
        assert out["data"].get("conflict") is True
        assert "déjà un rendez-vous" in out["response"]
