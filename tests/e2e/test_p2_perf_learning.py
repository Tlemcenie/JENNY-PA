"""Faits client revus : last_seen gardé."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.customer_fact import CustomerFact
from jenny.engine.conversation_engine import EngineResponse
from jenny.services.learning_service import persist_engine_signals


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _persist(bid, cid, facts) -> None:  # type: ignore[no-untyped-def]
    """Comme les webhooks : session à part."""
    result = EngineResponse(response_text="Noté !", intent="faq", extracted_facts=facts)
    async with async_session_factory() as s:
        await persist_engine_signals(
            s,
            business_id=bid,
            customer_id=cid,
            conversation_id=None,
            channel="whatsapp",
            result=result,
        )


@pytest.mark.asyncio
async def test_seen_again_fact_is_committed(db_tables: None) -> None:
    async with async_session_factory() as s, s.begin():
        biz = Business(name="Salon", slug=f"salon-{uuid4().hex[:8]}")
        s.add(biz)
        await s.flush()
        cust = Customer(business_id=biz.id, full_name="Léa")
        s.add(cust)
        await s.flush()
        bid, cid = biz.id, cust.id

    facts = [{"fact": "Allergique à l'ammoniaque", "kind": "allergy"}]
    await _persist(bid, cid, facts)
    old = datetime.now(UTC) - timedelta(days=30)
    async with async_session_factory() as s, s.begin():
        await s.execute(update(CustomerFact).values(last_seen_at=old))

    # même fait, revu plus tard
    await _persist(bid, cid, facts)
    async with async_session_factory() as s:
        rows = (await s.execute(select(CustomerFact))).scalars().all()
    assert len(rows) == 1
    seen = rows[0].last_seen_at
    seen = seen if seen.tzinfo else seen.replace(tzinfo=UTC)
    assert seen > old + timedelta(days=29)
