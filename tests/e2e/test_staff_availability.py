"""Tests : coiffeurs (multi-fauteuils) dans les dispos, la résa chat et le report."""

from __future__ import annotations

import itertools
import os
import time as _time
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.book_appointment_db import BookAppointmentDBAction
from jenny.actions.handlers.manage_appointment import ManageAppointmentAction
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.staff import Staff, StaffSkill
from jenny.engine.state_manager import ConversationState
from jenny.llm.prompts import PromptBuilder
from jenny.services.availability import (
    find_free_staff,
    free_slots_for_day,
    free_slots_with_staff,
    next_free_slots,
    spread_slots,
)

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
    """Jour futur (fuseau Paris)."""
    return (datetime.now(_PARIS) + timedelta(days=offset)).date()


def _at(day: date, hour: int, minute: int = 0, tz: ZoneInfo = _PARIS) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(UTC)


def _date_txt(day: date) -> str:
    return f"{day.day:02d}/{day.month:02d}/{day.year}"


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _seed(
    staff: tuple[str, ...] = (),
    *,
    tz: str = "Europe/Paris",
    hours: dict | None = None,
) -> tuple[Business, dict[str, Staff], dict[str, Prestation]]:
    """Salon + prestations + coiffeurs (dans l'ordre)."""
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(),
            name="Salon",
            slug=f"s-{uuid4().hex[:6]}",
            timezone=tz,
            business_hours=hours or _OPEN_ALL,
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


async def _add_skill(member: Staff, presta: Prestation) -> None:
    async with async_session_factory() as s, s.begin():
        s.add(StaffSkill(staff_id=member.id, prestation_id=presta.id))


async def _add_appt(
    biz: Business,
    start: datetime,
    minutes: int = 30,
    *,
    staff: Staff | None = None,
    status: str = "scheduled",
    title: str = "Coupe",
) -> Appointment:
    async with async_session_factory() as s, s.begin():
        appt = Appointment(
            business_id=biz.id,
            staff_id=staff.id if staff else None,
            title=title,
            channel="chat",
            start_at=start,
            end_at=start + timedelta(minutes=minutes),
            status=status,
            created_by="test",
        )
        s.add(appt)
    return appt


async def _all_appts(biz: Business) -> list[Appointment]:
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


async def _book(biz: Business, service: str, day: date, time_txt: str, **extra) -> dict:
    params = {
        "business_id": str(biz.id),
        "service": service,
        "date": _date_txt(day),
        "time": time_txt,
    }
    params.update(extra)
    return await BookAppointmentDBAction().execute(params)


# ── Salon solo : rien ne change ──────────────────────────────────────────────


class TestSoloSalonUnchanged:
    async def test_grid_is_duration_step_minus_booked(self, db_tables) -> None:
        biz, _, _ = await _seed()
        day = _day()
        await _add_appt(biz, _at(day, 10))
        async with async_session_factory() as s:
            slots = await free_slots_for_day(s, biz.id, day, 30)
            pairs = await free_slots_with_staff(s, biz.id, day, 30)
        expected = [
            _at(day, 9) + timedelta(minutes=30 * i)
            for i in range(20)
            if _at(day, 9) + timedelta(minutes=30 * i) != _at(day, 10)
        ]
        assert slots == expected
        assert [p[0] for p in pairs] == expected and all(p[1] == [] for p in pairs)

    async def test_45_min_grid_kept(self, db_tables) -> None:
        biz, _, _ = await _seed()
        day = _day()
        async with async_session_factory() as s:
            slots = await free_slots_for_day(s, biz.id, day, 45)
        assert slots[:3] == [_at(day, 9), _at(day, 9, 45), _at(day, 10, 30)]

    async def test_same_slot_twice_is_refused(self, db_tables) -> None:
        biz, _, _ = await _seed()
        day = _day()
        first = await _book(biz, "coupe", day, "10h")
        assert first["success"], first
        assert first["staff_name"] is None and first["staff_id"] is None
        second = await _book(biz, "coupe", day, "10h")
        assert second["success"] is False and second.get("conflict") is True
        assert len(await _all_appts(biz)) == 1

    async def test_inactive_staff_means_solo(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa",))
        async with async_session_factory() as s, s.begin():
            m = await s.get(Staff, members["Léa"].id)
            m.is_active = False
        day = _day()
        async with async_session_factory() as s:
            slots = await free_slots_for_day(s, biz.id, day, 30)
        assert slots[1] - slots[0] == timedelta(minutes=30)  # grille historique
        res = await _book(biz, "coupe", day, "10h")
        assert res["success"] and res["staff_id"] is None


# ── Plusieurs coiffeurs ──────────────────────────────────────────────────────


class TestMultiChair:
    async def test_two_stylists_same_slot(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        a = await _book(biz, "coupe", day, "10h")
        b = await _book(biz, "coupe", day, "10h")
        assert a["success"] and b["success"], (a, b)
        assert a["staff_name"] == "Léa" and b["staff_name"] == "Marc"
        assert "avec Léa" in a["message"]
        third = await _book(biz, "coupe", day, "10h")
        assert third["success"] is False and third.get("conflict") is True
        assert third["alternatives_text"] and "à 10h00" not in third["alternatives_text"]
        rows = await _all_appts(biz)
        assert {r.staff_id for r in rows} == {members["Léa"].id, members["Marc"].id}

    async def test_slot_free_while_one_stylist_left(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        async with async_session_factory() as s:
            pairs = dict(await free_slots_with_staff(s, biz.id, day, 30))
            assert [m.display_name for m in pairs[_at(day, 10)]] == ["Marc"]
            await _add_appt(biz, _at(day, 10), staff=members["Marc"])
        async with async_session_factory() as s:
            pairs = dict(await free_slots_with_staff(s, biz.id, day, 30))
        assert _at(day, 10) not in pairs
        assert _at(day, 9, 30) in pairs and _at(day, 10, 30) in pairs

    async def test_grid_every_15_min_but_readable_list(self, db_tables) -> None:
        biz, _, _ = await _seed(("Léa",))
        day = _day()
        async with async_session_factory() as s:
            pairs = await free_slots_with_staff(s, biz.id, day, 30)
            slots = await free_slots_for_day(s, biz.id, day, 30)
            nxt = await next_free_slots(s, biz.id, 30, from_day=day)
        assert pairs[1][0] - pairs[0][0] == timedelta(minutes=15)
        assert all(b - a >= timedelta(minutes=30) for a, b in itertools.pairwise(slots))
        assert nxt == slots[:4]

    async def test_15_min_grid_fills_gaps(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa",))
        day = _day()
        # RDV 9h-9h45 : 9h45 devient possible
        await _add_appt(biz, _at(day, 9), 45, staff=members["Léa"])
        async with async_session_factory() as s:
            slots = await free_slots_for_day(s, biz.id, day, 30)
        assert slots[0] == _at(day, 9, 45)

    async def test_unassigned_rdv_takes_a_chair(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        await _add_appt(biz, _at(day, 10))  # ancien RDV sans coiffeur
        async with async_session_factory() as s:
            pick = await find_free_staff(s, biz.id, _at(day, 10), _at(day, 10, 30))
        assert pick.free is False and pick.has_staff is True

    async def test_salon_block_blocks_everyone(self, db_tables) -> None:
        biz, _, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 12), 120, status="blocked", title="Indisponible")
        async with async_session_factory() as s:
            pairs = dict(await free_slots_with_staff(s, biz.id, day, 30))
        assert _at(day, 12) not in pairs and _at(day, 13, 30) not in pairs
        assert _at(day, 14) in pairs

    async def test_stylist_block_only_blocks_him(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 12), 60, staff=members["Léa"], status="blocked")
        res = await _book(biz, "coupe", day, "12h")
        assert res["success"] and res["staff_name"] == "Marc"


class TestSkills:
    async def test_skill_is_respected(self, db_tables) -> None:
        biz, members, prestas = await _seed(("Léa", "Marc", "Zoé"))
        await _add_skill(members["Léa"], prestas["Coupe"])
        await _add_skill(members["Marc"], prestas["Couleur"])
        day = _day()
        # Léa ne fait pas la couleur
        res = await _book(biz, "couleur", day, "10h")
        assert res["success"] and res["staff_name"] == "Marc"
        # coupe + couleur : seule Zoé (sans compétence) sait tout faire
        both = await _book(biz, "coupe et couleur", day, "14h")
        assert both["success"] and both["staff_name"] == "Zoé"

    async def test_nobody_competent_is_a_conflict(self, db_tables) -> None:
        biz, members, prestas = await _seed(("Léa",))
        await _add_skill(members["Léa"], prestas["Coupe"])
        res = await _book(biz, "couleur", _day(), "10h")
        assert res["success"] is False and res.get("conflict") is True
        assert await _all_appts(biz) == []

    async def test_proposals_follow_skills(self, db_tables) -> None:
        biz, members, prestas = await _seed(("Léa", "Marc"))
        await _add_skill(members["Léa"], prestas["Coupe"])
        await _add_skill(members["Marc"], prestas["Couleur"])
        day = _day()
        await _add_appt(biz, _at(day, 9), 120, staff=members["Marc"])
        async with async_session_factory() as s:
            slots = await free_slots_for_day(
                s, biz.id, day, 60, prestation_ids=[prestas["Couleur"].id]
            )
        assert slots[0] == _at(day, 11)


class TestStaffTaken:
    async def test_busy_stylist_gives_other(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        await _add_appt(biz, _at(day, 10), staff=members["Léa"])
        res = await _book(biz, "coupe", day, "10h")
        assert res["success"] and res["staff_name"] == "Marc"

    async def test_working_hours(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day.weekday()]
        async with async_session_factory() as s, s.begin():
            lea = await s.get(Staff, members["Léa"].id)
            lea.working_hours = {key: ["09:00", "13:00"]}  # matin seulement
            marc = await s.get(Staff, members["Marc"].id)
            marc.working_hours = {key: None}  # jour off
        assert (await _book(biz, "coupe", day, "10h"))["staff_name"] == "Léa"
        late = await _book(biz, "coupe", day, "15h")
        assert late["success"] is False and late.get("conflict") is True

    async def test_requested_stylist(self, db_tables) -> None:
        biz, _members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        res = await _book(biz, "coupe", day, "10h", staff="marc")
        assert res["success"] and res["staff_name"] == "Marc"

    async def test_reschedule_keeps_stylist(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        appt = await _add_appt(biz, _at(day, 10), staff=members["Marc"])
        res = await ManageAppointmentAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "operation": "reschedule",
                "date": _date_txt(day),
                "time": "15h",
            }
        )
        assert res["success"], res
        assert res["staff_changed"] is False and "avec" not in res["when"]
        async with async_session_factory() as s:
            fresh = await s.get(Appointment, appt.id)
        assert fresh.staff_id == members["Marc"].id
        assert _utc(fresh.start_at) == _at(day, 15)

    async def test_reschedule_switches_stylist_when_taken(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        appt = await _add_appt(biz, _at(day, 10), staff=members["Marc"])
        await _add_appt(biz, _at(day, 16), staff=members["Marc"])
        res = await ManageAppointmentAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "operation": "reschedule",
                "date": _date_txt(day),
                "time": "16h",
            }
        )
        assert res["success"], res
        assert res["staff_changed"] is True and res["when"].endswith("avec Léa")
        async with async_session_factory() as s:
            fresh = await s.get(Appointment, appt.id)
        assert fresh.staff_id == members["Léa"].id

    async def test_reschedule_conflict_when_all_taken(self, db_tables) -> None:
        biz, members, _ = await _seed(("Léa", "Marc"))
        day = _day()
        appt = await _add_appt(biz, _at(day, 10), staff=members["Marc"])
        await _add_appt(biz, _at(day, 16), staff=members["Marc"])
        await _add_appt(biz, _at(day, 16), staff=members["Léa"])
        res = await ManageAppointmentAction().execute(
            {
                "business_id": str(biz.id),
                "appointment_id": str(appt.id),
                "operation": "reschedule",
                "date": _date_txt(day),
                "time": "16h",
            }
        )
        assert res["success"] is False and res.get("conflict") is True


# ── Fuseau B1 ────────────────────────────────────────────────────────────────


class TestTimezoneB1:
    async def test_late_evening_booking_uses_salon_day(self, db_tables) -> None:
        # serveur UTC-11, salon UTC+14 : jamais le même jour
        salon_tz = ZoneInfo("Pacific/Kiritimati")
        biz, _, _ = await _seed(tz="Pacific/Kiritimati")
        before = datetime.now(salon_tz).date()
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Pago_Pago"
        _time.tzset()
        try:
            assert datetime.now().date() < before  # le serveur est « la veille »
            res = await BookAppointmentDBAction().execute(
                {"business_id": str(biz.id), "service": "coupe", "date": "demain", "time": "15h"}
            )
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            _time.tzset()
        after = datetime.now(salon_tz).date()
        assert res["success"], res
        (appt,) = await _all_appts(biz)
        booked_day = _utc(appt.start_at).astimezone(salon_tz).date()
        assert booked_day in {before + timedelta(days=1), after + timedelta(days=1)}


# ── Prompt ───────────────────────────────────────────────────────────────────


class TestPromptStaff:
    def test_booking_line_mentions_stylist(self) -> None:
        state = ConversationState()
        state.action_result = {
            "success": True,
            "service": "Coupe",
            "day": "mardi 12/11",
            "time": "10h00",
            "staff_name": "Léa",
        }
        prompt = PromptBuilder().build_system_prompt(state)
        assert "prestation : Coupe avec Léa · jour : mardi 12/11" in prompt

    def test_booking_line_without_stylist(self) -> None:
        state = ConversationState()
        state.action_result = {"success": True, "service": "Coupe", "day": "mardi", "time": "10h00"}
        prompt = PromptBuilder().build_system_prompt(state)
        assert "prestation : Coupe · jour : mardi" in prompt


def test_spread_slots_keeps_gap() -> None:
    base = datetime(2030, 1, 1, 9, tzinfo=UTC)
    slots = [base + timedelta(minutes=15 * i) for i in range(8)]
    assert spread_slots(slots, 45) == [
        base,
        base + timedelta(minutes=45),
        base + timedelta(minutes=90),
    ]
