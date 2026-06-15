"""Régression : un message WhatsApp entrant rattache le client au moteur (donc au RDV).

Avant le correctif, ``EngineRequest`` était construit sans ``customer_id`` sur les
canaux entrants : Jenny créait bien un profil client (numéro + nom de profil) à
l'ingestion, mais le RDV pris ensuite n'était PAS relié à ce client (RDV orphelin
dans l'agenda). Ce test verrouille le fait que le ``customer_id`` résolu est bien
transmis au moteur.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.api.routes.webhooks as wh
import jenny.domain.models  # noqa: F401
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.engine.conversation_engine import EngineResponse


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


class _FakeEngine:
    """Capture la requête moteur sans appeler le LLM."""

    def __init__(self) -> None:
        self.last_req = None

    async def process(self, req):
        self.last_req = req
        return EngineResponse(response_text="Bonjour Marie !", intent="greeting")


@pytest.mark.asyncio
async def test_whatsapp_threads_customer_id_to_engine(db_tables: None, monkeypatch) -> None:
    bid = uuid4()
    async with async_session_factory() as s, s.begin():
        s.add(Business(id=bid, name="Salon", slug=f"s-{uuid4().hex[:6]}"))

    fake = _FakeEngine()
    monkeypatch.setattr(wh, "_get_engine", lambda: fake)

    async def _no_send(recipient: str, content: str) -> bool:
        return True

    monkeypatch.setattr(wh._whatsapp, "send_reply", _no_send)

    phone = "33612345678"
    msg_data = {
        "from": phone,
        "id": "wamid.test1",
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": "Bonjour, je voudrais une coupe"},
    }
    await wh._whatsapp_ingest_and_reply(msg_data, str(bid), {phone: "Marie"})

    # Le client est créé depuis le numéro WhatsApp + le nom de profil.
    async with async_session_factory() as s:
        cust = (
            await s.execute(select(Customer).where(Customer.business_id == bid))
        ).scalar_one()
    assert cust.phone == phone
    assert cust.full_name == "Marie"

    # Le moteur a reçu le customer_id résolu (sinon le RDV serait orphelin).
    assert fake.last_req is not None
    assert str(fake.last_req.customer_id) == str(cust.id)
    assert fake.last_req.channel == "whatsapp"
