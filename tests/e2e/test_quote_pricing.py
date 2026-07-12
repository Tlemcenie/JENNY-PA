"""Devis sur question de prix + téléchargement du PDF.

- Une question de PRIX sur une prestation du catalogue déclenche un VRAI devis
  (intent « quote », action_result avec pdf_url + référence).
- Sans catalogue, on NE force PAS le devis (comportement FAQ préservé — protège
  le banc d'essai).
- L'endpoint GET /quotes/{id}/pdf renvoie un PDF, scopé au business (404 sinon).
"""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.quote import Quote
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import build_engine
from jenny.engine.state_manager import StateManager

_OPEN_ALL = {k: ["09:00", "19:00"] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
_CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]


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


async def _seed_business(*, with_catalog: bool) -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(
            id=uuid4(), name="Salon Léa", slug=f"s-{uuid4().hex[:6]}", business_hours=_OPEN_ALL
        )
        s.add(biz)
        if with_catalog:
            s.add(
                Prestation(
                    business_id=biz.id, name="Coupe femme", price_cents=3900, duration_minutes=45
                )
            )
            s.add(
                Prestation(
                    business_id=biz.id, name="Balayage", price_cents=8000, duration_minutes=120
                )
            )
    return biz


def _req(conv, biz, msg, catalog):
    return EngineRequest(
        conversation_id=conv,
        business_id=biz.id,
        message_text=msg,
        catalog_services=catalog,
    )


class TestPricingTriggersQuote:
    async def test_price_question_with_catalog_makes_quote(self, db_tables) -> None:
        biz = await _seed_business(with_catalog=True)
        eng = build_engine(state_manager=StateManager())
        eng.response_generator = None  # message déterministe de l'action
        r = await eng.process(_req(uuid4(), biz, "c'est combien une coupe femme ?", _CATALOG))
        assert r.intent == "quote"
        ar = r.action_result or {}
        assert ar.get("success") is True
        assert ar.get("pdf_url", "").endswith("/pdf")
        assert ar.get("reference", "").startswith("DEV-")
        assert ar.get("total_eur") == 39.0
        # Devis réellement persisté.
        async with async_session_factory() as s:
            qid = await s.scalar(select(Quote.id).where(Quote.business_id == biz.id))
        assert qid is not None

    async def test_price_question_without_catalog_stays_faq(self, db_tables) -> None:
        # Sans catalogue (cas du banc d'essai) : on NE force PAS le devis.
        biz = await _seed_business(with_catalog=False)
        eng = build_engine(state_manager=StateManager())
        eng.response_generator = None
        r = await eng.process(_req(uuid4(), biz, "c'est combien une coupe femme ?", None))
        assert r.intent != "quote"


class TestQuotePdfEndpoint:
    @pytest.fixture
    async def client(self) -> AsyncClient:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
            yield c

    async def _make_quote(self, biz: Business) -> Quote:
        async with async_session_factory() as s, s.begin():
            q = Quote(
                business_id=biz.id,
                reference=f"DEV-{uuid4().hex[:8].upper()}",
                items=[{"name": "Coupe femme", "price_eur": 39.0, "duration_minutes": 45}],
                total_cents=3900,
                total_ht_cents=3250,
                total_tva_cents=650,
                vat_rate=0.20,
                currency="EUR",
                status="draft",
                valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
            )
            s.add(q)
        async with async_session_factory() as s:
            return await s.scalar(select(Quote).where(Quote.business_id == biz.id))

    @staticmethod
    def _auth(biz: Business) -> dict[str, str]:
        token = create_access_token(uuid4(), "gerant@test.fr", [biz.id])
        return {"Authorization": f"Bearer {token}"}

    async def test_download_returns_pdf(self, db_tables, client: AsyncClient) -> None:
        biz = await _seed_business(with_catalog=True)
        quote = await self._make_quote(biz)
        r = await client.get(f"/api/v1/quotes/{quote.id}/pdf", headers=self._auth(biz))
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"  # vrai PDF

    async def test_other_business_gets_404(self, db_tables, client: AsyncClient) -> None:
        biz = await _seed_business(with_catalog=True)
        other = await _seed_business(with_catalog=False)
        quote = await self._make_quote(biz)
        r = await client.get(f"/api/v1/quotes/{quote.id}/pdf", headers=self._auth(other))
        assert r.status_code == 404  # isolation multi-tenant

    async def test_requires_auth(self, db_tables, client: AsyncClient) -> None:
        biz = await _seed_business(with_catalog=True)
        quote = await self._make_quote(biz)
        r = await client.get(f"/api/v1/quotes/{quote.id}/pdf")
        assert r.status_code == 401
