"""Webhooks : connexion de route rendue avant la tâche."""

from __future__ import annotations

import inspect
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

import jenny.api.routes.webhooks as wh
import jenny.domain.models  # noqa: F401
from jenny.api.dependencies import get_db
from jenny.api.main import create_app
from jenny.db import session as db_session
from jenny.db.session import async_session_factory, session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.channel_account import ChannelAccount
from jenny.domain.models.conversation import Conversation
from jenny.engine.conversation_engine import EngineResponse
from tests.conftest import TEST_DB_URL

pytestmark = pytest.mark.usefixtures("db_tables")

PNID = "PNID-P4-ROUTES"


@pytest.fixture
async def route_pool(monkeypatch: pytest.MonkeyPatch):
    """Pool des routes : une connexion."""
    eng = create_async_engine(
        TEST_DB_URL,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    monkeypatch.setattr(db_session, "request_session_factory", session_factory(eng))
    yield eng
    await eng.dispose()


class _SpyEngine:
    """Faux LLM : regarde le pool."""

    def __init__(self, pool_engine) -> None:  # type: ignore[no-untyped-def]
        self.pool_engine = pool_engine
        self.checked_out: int | None = None
        self.route_conn_ok = False

    async def process(self, req, on_token=None):  # type: ignore[no-untyped-def]
        self.checked_out = self.pool_engine.pool.checkedout()
        # la seule connexion est libre
        async with db_session.request_session_factory() as s:
            await s.execute(text("SELECT 1"))
        self.route_conn_ok = True
        return EngineResponse(response_text="Bonjour !", intent="greeting")


async def _salon_whatsapp() -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}")
        s.add(biz)
        s.add(ChannelAccount(business_id=biz.id, channel="whatsapp", external_account_id=PNID))
    return biz


def _payload() -> dict:
    msg = {
        "from": "33600000001",
        "id": f"wamid.{uuid4().hex}",
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": "Bonjour"},
    }
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "1", "phone_number_id": PNID},
        "contacts": [{"wa_id": "33600000001", "profile": {"name": "Marie"}}],
        "messages": [msg],
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "W", "changes": [{"field": "messages", "value": value}]}],
    }


async def _no_send(*_a, **_kw) -> bool:
    return True


async def test_whatsapp_rend_la_connexion_avant_la_tache(
    route_pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    biz = await _salon_whatsapp()
    spy = _SpyEngine(route_pool)

    async def _engine() -> _SpyEngine:
        return spy

    monkeypatch.setattr(wh, "_get_engine", _engine)
    monkeypatch.setattr(wh._whatsapp, "send_reply", _no_send)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/webhooks/whatsapp", json=_payload())
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    # la tâche a tourné
    assert spy.checked_out is not None, "tâche de fond non lancée"
    # route fermée pendant le LLM
    assert spy.checked_out == 0
    assert spy.route_conn_ok
    # tâche : sa propre session
    async with async_session_factory() as s:
        conv = (
            await s.execute(select(Conversation).where(Conversation.business_id == biz.id))
        ).scalar_one()
    assert conv.channel == "whatsapp"


async def test_temoin_scope_requete_garde_la_connexion(route_pool) -> None:
    """Témoin : sans scope, la connexion reste prise."""
    seen: list[int] = []
    app = FastAPI()

    async def _task() -> None:
        seen.append(route_pool.pool.checkedout())

    @app.post("/x")
    async def _route(
        bg: BackgroundTasks, db: Annotated[AsyncSession, Depends(get_db)]
    ) -> dict:
        await db.execute(text("SELECT 1"))
        bg.add_task(_task)
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/x")).status_code == 200
    # la mesure voit bien le bug
    assert seen == [1]


def _db_scopes(route: APIRoute) -> list[str | None]:
    """Scopes des get_db de la route."""
    return [d.scope for d in route.dependant.dependencies if d.call is get_db]


def test_toutes_les_routes_webhook_ferment_tot() -> None:
    """Chaque route webhook : scope function."""
    routes = [r for r in wh.router.routes if isinstance(r, APIRoute)]
    with_db = [r for r in routes if _db_scopes(r)]
    with_tasks = [
        r
        for r in routes
        if any(
            p.annotation in (BackgroundTasks, "BackgroundTasks")
            for p in inspect.signature(r.endpoint).parameters.values()
        )
    ]
    # 4 canaux en tâche de fond
    assert {r.path for r in with_tasks} >= {
        "/webhooks/whatsapp",
        "/webhooks/instagram",
        "/webhooks/twitter",
        "/webhooks/snapchat",
    }
    assert with_db
    for r in with_db:
        assert _db_scopes(r) == ["function"], r.path
    assert inspect.iscoroutinefunction(wh._get_engine)
