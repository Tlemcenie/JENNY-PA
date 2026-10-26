"""Passe 3 résa : place libérée depuis l'agenda, sur SQLite réel.

La passe de remplissage est vraiment lancée (await), le créneau exact est
tracé, et un RDV de coiffeur en pause ne prévient personne.
Seul l'envoi SMS est simulé.
"""

from __future__ import annotations

import asyncio
import gc
import warnings
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.actions.handlers.manage_appointment import ManageAppointmentAction
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import SlotOffer
from jenny.domain.models.customer import Customer
from jenny.domain.models.notification import Notification
from jenny.domain.models.staff import Staff
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services import gap_filler

_OPEN = {k: ["00:00", "23:59"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_URL = "/api/v1/appointments"


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


@pytest.fixture
def sms(monkeypatch) -> list[tuple[str, str]]:
    """SMS simulé : tout part."""
    sent: list[tuple[str, str]] = []

    async def fake(self, to, body):
        sent.append((to, body))
        return SimpleNamespace(success=True)

    monkeypatch.setattr("jenny.notifications.sms_sender.SmsSender.send_sms", fake)
    return sent


@pytest.fixture
def runs(monkeypatch) -> list[UUID]:
    """Passes lancées, sans Redis."""
    from jenny.core.config import get_settings

    seen: list[UUID] = []

    async def fake_run(business_id, **kw):
        seen.append(business_id)

    monkeypatch.setattr(get_settings(), "redis_url", "")
    monkeypatch.setattr(gap_filler, "run_for_business", fake_run)
    yield seen
    # pas de tâche orpheline
    for task in list(gap_filler._pending.values()):
        if not task.done() and not task.get_loop().is_closed():
            task.cancel()
    gap_filler._pending.clear()


def _now() -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _headers(biz: Business) -> dict[str, str]:
    token = create_access_token(uuid4(), "gerant@test.fr", [biz.id])
    return {"Authorization": f"Bearer {token}"}


async def _biz(*staff: tuple[str, bool]) -> tuple[Business, dict[str, Staff]]:
    async with async_session_factory() as s, s.begin():
        b = Business(id=uuid4(), name="Salon Zoé", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN)
        s.add(b)
        members = {}
        for i, (name, active) in enumerate(staff):
            m = Staff(
                id=uuid4(),
                business_id=b.id,
                display_name=name,
                is_active=active,
                created_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            s.add(m)
            members[name] = m
    return b, members


async def _cust(biz: Business, name: str, phone: str) -> Customer:
    async with async_session_factory() as s, s.begin():
        c = Customer(id=uuid4(), business_id=biz.id, full_name=name, phone=phone)
        s.add(c)
    return c


async def _appt(
    biz: Business, start: datetime, minutes: int = 30, *, cust=None, staff=None
) -> Appointment:
    async with async_session_factory() as s, s.begin():
        a = Appointment(
            id=uuid4(),
            business_id=biz.id,
            customer_id=cust.id if cust else None,
            staff_id=staff.id if staff else None,
            title="Coupe",
            channel="chat",
            start_at=start,
            end_at=start + timedelta(minutes=minutes),
            status="scheduled",
            created_by="test",
        )
        s.add(a)
    return a


async def _attente(biz: Business, cust: Customer) -> WaitlistEntry:
    async with async_session_factory() as s, s.begin():
        e = WaitlistEntry(
            business_id=biz.id, customer_id=cust.id, service="Coupe", customer_name=cust.full_name
        )
        s.add(e)
    return e


async def _state(biz: Business, entry: WaitlistEntry) -> tuple[str, list[SlotOffer], int]:
    async with async_session_factory() as s:
        status = (await s.get(WaitlistEntry, entry.id)).status
        offers = list((await s.execute(select(SlotOffer))).scalars().all())
        notes = (
            await s.execute(select(Notification).where(Notification.kind == "waitlist_match"))
        ).scalars().all()
    return status, offers, len(notes)


async def _wait_pass(biz: Business) -> None:
    """Attend la passe (délai 2 s)."""
    task = gap_filler._pending.get(biz.id)
    assert task is not None, "aucune passe lancée"
    await asyncio.wait_for(task, timeout=10)


# ── item 1 : await + créneau exact ──


class TestPasseLancee:
    async def test_annulation_lance_la_passe(self, db_tables, client, sms, runs) -> None:
        biz, _ = await _biz()
        sophie = await _cust(biz, "Sophie", "+33611111111")
        wendy = await _cust(biz, "Wendy", "+33622222222")
        start = _now() + timedelta(hours=30)
        a = await _appt(biz, start, 45, cust=sophie)
        entry = await _attente(biz, wendy)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            r = await client.patch(
                f"{_URL}/{a.id}", headers=_headers(biz), json={"status": "cancelled"}
            )
            assert r.status_code == 200 and r.json()["status"] == "cancelled"
            await _wait_pass(biz)
            gc.collect()
        # avant : coroutine jamais attendue
        assert not [w for w in caught if "never awaited" in str(w.message)]
        assert runs == [biz.id]

        status, offers, notes = await _state(biz, entry)
        assert status == "notified" and notes == 1
        # créneau exact, malgré le commit
        assert len(offers) == 1
        assert _aware(offers[0].slot_start) == start and offers[0].duration_minutes == 45
        assert offers[0].customer_id == wendy.id and offers[0].channel == "sms"
        assert len(sms) == 1 and "assistante virtuelle" in sms[0][1]

    async def test_suppression_trace_le_creneau(self, db_tables, client, sms, runs) -> None:
        biz, _ = await _biz()
        wendy = await _cust(biz, "Wendy", "+33622222222")
        start = _now() + timedelta(hours=26)
        a = await _appt(biz, start, 60)
        entry = await _attente(biz, wendy)

        r = await client.delete(f"{_URL}/{a.id}", headers=_headers(biz))
        assert r.status_code == 200
        await _wait_pass(biz)
        assert runs == [biz.id]
        status, offers, _ = await _state(biz, entry)
        assert status == "notified"
        assert _aware(offers[0].slot_start) == start and offers[0].duration_minutes == 60

    async def test_personne_en_attente_une_seule_passe(self, db_tables, client, runs) -> None:
        biz, _ = await _biz()
        a = await _appt(biz, _now() + timedelta(hours=26))
        r = await client.patch(
            f"{_URL}/{a.id}", headers=_headers(biz), json={"status": "cancelled"}
        )
        assert r.status_code == 200
        await _wait_pass(biz)
        # deux appels, une passe
        assert runs == [biz.id]

    async def test_deplacement_libere_lancien_creneau(self, db_tables, client, sms, runs) -> None:
        biz, _ = await _biz()
        wendy = await _cust(biz, "Wendy", "+33622222222")
        old = _now() + timedelta(hours=30)
        a = await _appt(biz, old, 30)
        entry = await _attente(biz, wendy)
        new = old + timedelta(days=1)
        r = await client.patch(
            f"{_URL}/{a.id}",
            headers=_headers(biz),
            json={"start_at": new.isoformat(), "end_at": (new + timedelta(minutes=30)).isoformat()},
        )
        assert r.status_code == 200
        await _wait_pass(biz)
        status, offers, _ = await _state(biz, entry)
        assert status == "notified" and _aware(offers[0].slot_start) == old

    async def test_rallonge_ne_libere_rien(self, db_tables, client, sms, runs) -> None:
        biz, _ = await _biz()
        wendy = await _cust(biz, "Wendy", "+33622222222")
        start = _now() + timedelta(hours=30)
        a = await _appt(biz, start, 30)
        entry = await _attente(biz, wendy)
        r = await client.patch(
            f"{_URL}/{a.id}",
            headers=_headers(biz),
            json={"end_at": (start + timedelta(minutes=45)).isoformat()},
        )
        assert r.status_code == 200
        status, offers, notes = await _state(biz, entry)
        assert status == "waiting" and offers == [] and notes == 0
        assert biz.id not in gap_filler._pending and sms == []


# ── item 3 : coiffeur en pause ──


class TestCoiffeurEnPause:
    async def test_annulation_dashboard_ne_previent_personne(
        self, db_tables, client, sms, runs
    ) -> None:
        biz, staff = await _biz(("Léa", False), ("Marc", True))
        wendy = await _cust(biz, "Wendy", "+33622222222")
        a = await _appt(biz, _now() + timedelta(hours=30), staff=staff["Léa"])
        entry = await _attente(biz, wendy)

        r = await client.patch(
            f"{_URL}/{a.id}", headers=_headers(biz), json={"status": "cancelled"}
        )
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        status, offers, notes = await _state(biz, entry)
        # sa place reste dans la file
        assert status == "waiting" and offers == [] and notes == 0 and sms == []
        # rien de libéré : pas de passe
        assert biz.id not in gap_filler._pending and runs == []

    async def test_coiffeur_actif_previent(self, db_tables, client, sms, runs) -> None:
        biz, staff = await _biz(("Léa", True), ("Marc", True))
        wendy = await _cust(biz, "Wendy", "+33622222222")
        a = await _appt(biz, _now() + timedelta(hours=30), staff=staff["Léa"])
        entry = await _attente(biz, wendy)
        r = await client.patch(
            f"{_URL}/{a.id}", headers=_headers(biz), json={"status": "cancelled"}
        )
        assert r.status_code == 200
        await _wait_pass(biz)
        status, offers, notes = await _state(biz, entry)
        assert status == "notified" and len(offers) == 1 and notes == 1

    async def test_annulation_client_en_pause(self, db_tables, sms, runs) -> None:
        biz, staff = await _biz(("Léa", False), ("Marc", True))
        sophie = await _cust(biz, "Sophie", "+33611111111")
        wendy = await _cust(biz, "Wendy", "+33622222222")
        await _appt(biz, _now() + timedelta(hours=30), cust=sophie, staff=staff["Léa"])
        entry = await _attente(biz, wendy)
        res = await ManageAppointmentAction().execute(
            {"business_id": str(biz.id), "customer_id": str(sophie.id), "operation": "cancel"}
        )
        assert res["success"] and res["operation"] == "cancel"
        status, offers, notes = await _state(biz, entry)
        assert status == "waiting" and offers == [] and notes == 0 and sms == []

    async def test_blocage_salon_respecte_en_pause(self, db_tables, client, runs) -> None:
        biz, staff = await _biz(("Léa", False), ("Marc", True))
        start = _now() + timedelta(hours=30)
        async with async_session_factory() as s, s.begin():
            s.add(
                Appointment(
                    business_id=biz.id,
                    title="Indisponible",
                    channel="block",
                    start_at=start,
                    end_at=start + timedelta(hours=2),
                    status="blocked",
                    created_by="test",
                )
            )
        body = {
            "title": "Coupe",
            "start_at": (start + timedelta(minutes=30)).isoformat(),
            "end_at": (start + timedelta(minutes=60)).isoformat(),
            "staff_id": str(staff["Léa"].id),
        }
        r = await client.post(_URL, headers=_headers(biz), json=body)
        # avant : 201 malgré le blocage
        assert r.status_code == 409
