"""Widget : états bornés par le seul cache moteur."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.api.routes import public_chat
from jenny.api.routes.public_chat import conversation_id_for
from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.engine.factory import get_engine
from jenny.engine.state_manager import MEMORY_MAX_STATES, MEMORY_TTL_SECONDS, StateManager


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://w") as c:
        yield c


@pytest.fixture
async def salon(db_tables) -> Business:
    public_chat.reset_limits()
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon Léa", slug=f"lea-{uuid4().hex[:6]}")
        s.add(biz)
    yield biz
    public_chat.reset_limits()


async def _say(client: AsyncClient, slug: str, vid: str, ip: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/public/chat/{slug}",
        json={"visitor_id": vid, "message": "Bonjour"},
        headers={"x-forwarded-for": f"10.0.0.1, {ip}"},
    )


def test_bornes_du_cache_moteur() -> None:
    """Bornes citées dans public_chat."""
    assert MEMORY_MAX_STATES == 5000
    assert MEMORY_TTL_SECONDS == 48 * 3600
    # plus de suivi côté widget
    for name in ("_STATES", "_track_state", "MAX_STATES", "EVICT_METHOD"):
        assert not hasattr(public_chat, name), name


async def test_widget_borne_par_le_lru_moteur(
    client: AsyncClient, salon: Business, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = StateManager(max_memory_states=2)
    monkeypatch.setattr(get_engine(), "state_manager", small)
    vids = [uuid4().hex for _ in range(3)]
    for i, vid in enumerate(vids):
        r = await _say(client, salon.slug, vid, f"198.51.100.{40 + i}")
        assert r.status_code == 200, r.text
    first, *rest = [conversation_id_for(salon.id, v) for v in vids]
    # le moteur borne, LRU
    assert small.get(first) is None
    assert all(small.get(c) is not None for c in rest)


async def test_visiteur_reprend_son_etat(client: AsyncClient, salon: Business) -> None:
    """Deux messages : même état moteur."""
    vid = uuid4().hex
    conv = conversation_id_for(salon.id, vid)
    assert (await _say(client, salon.slug, vid, "198.51.100.50")).status_code == 200
    state = get_engine().state_manager.get(conv)
    assert state is not None and state.turn_count >= 1
    turns = state.turn_count
    assert (await _say(client, salon.slug, vid, "198.51.100.50")).status_code == 200
    again = get_engine().state_manager.get(conv)
    assert again is not None and again.turn_count > turns
