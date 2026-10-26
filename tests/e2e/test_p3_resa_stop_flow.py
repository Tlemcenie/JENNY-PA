"""Passe 3 : un refus clair avec « pas » désinscrit vraiment (SQLite réel)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.services.offer_cap import apply_stop_reply, can_offer


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


async def _cliente() -> tuple[Business, Customer]:
    async with async_session_factory() as s, s.begin():
        b = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}")
        c = Customer(id=uuid4(), business_id=b.id, full_name="Alice", phone="+33600000001")
        s.add_all([b, c])
    return b, c


@pytest.mark.parametrize(
    ("text", "stop"),
    [
        ("je ne veux pas de pub, stop", True),
        ("stop, ne m'envoyez pas de messages", True),
        ("n'arrêtez pas", False),
        ("stop je voulais dire jeudi", False),
    ],
)
async def test_desinscription(db_tables, text: str, stop: bool) -> None:
    biz, alice = await _cliente()
    async with async_session_factory() as db:
        done = await apply_stop_reply(db, business_id=biz.id, customer_id=alice.id, text=text)
        await db.commit()
    assert done is stop
    async with async_session_factory() as db:
        fiche = await db.get(Customer, alice.id)
    # avant : refus ignoré
    assert (fiche.marketing_opt_out_at is not None) is stop
    assert can_offer(fiche) is (not stop)
