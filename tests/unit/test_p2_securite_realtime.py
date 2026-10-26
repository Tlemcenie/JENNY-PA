"""SSE sans connexion gardée, réponse widget livrée."""

from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.dependencies import get_db
from jenny.api.main import create_app
from jenny.api.routes import realtime
from jenny.connectors.reply_dispatch import send_channel_reply


async def test_widget_reply_counts_as_delivered() -> None:
    assert await send_channel_reply("widget", None, "On vous attend mardi !") is True


async def test_sse_releases_db_before_streaming(monkeypatch) -> None:
    log: list[str] = []

    async def _db():
        log.append("open")
        yield object()
        log.append("close")

    async def _stream(business_id, is_disconnected, **kw):
        # connexion déjà rendue ?
        log.append(f"stream:{business_id}")
        yield ": connected\n\n"

    monkeypatch.setattr(realtime, "sse_event_stream", _stream)
    app = create_app()
    app.dependency_overrides[get_db] = _db
    bid = uuid4()
    token = create_access_token(uuid4(), "a@b.fr", [bid])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/realtime/stream", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert log == ["open", "close", f"stream:{bid}"]


async def test_sse_still_needs_a_token() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/realtime/stream")
    assert r.status_code == 401
