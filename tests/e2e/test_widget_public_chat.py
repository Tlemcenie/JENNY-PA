"""Tests du chat public du widget."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.api.routes import public_chat
from jenny.api.routes.public_chat import conversation_id_for
from jenny.core.config import get_settings
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.message import Message

_PUBLIC_KEYS = {"response", "quick_replies", "handoff", "human", "quote", "payment"}


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://w") as c:
        yield c


@pytest.fixture
async def db_tables():
    public_chat.reset_limits()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    public_chat.reset_limits()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _salon(**kw) -> Business:
    fields = {
        "id": uuid4(),
        "name": "Salon Léa",
        "slug": f"lea-{uuid4().hex[:6]}",
        "email": "secret-owner@lea.fr",
        "phone": "+33611223344",
    }
    fields.update(kw)
    async with async_session_factory() as s, s.begin():
        biz = Business(**fields)
        s.add(biz)
    return biz


def _visitor() -> str:
    return str(uuid4())


class TestUnknownSalon:
    async def test_unknown_slug_404(self, client: AsyncClient, db_tables) -> None:
        r = await client.post(
            "/api/v1/public/chat/nope-xyz", json={"visitor_id": _visitor(), "message": "Bonjour"}
        )
        assert r.status_code == 404
        r = await client.get("/api/v1/public/chat/nope-xyz/config")
        assert r.status_code == 404

    async def test_inactive_salon_404(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon(is_active=False)
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            json={"visitor_id": _visitor(), "message": "Bonjour"},
        )
        assert r.status_code == 404
        assert (await client.get(f"/api/v1/public/chat/{biz.slug}/config")).status_code == 404

    async def test_weird_slug_404(self, client: AsyncClient, db_tables) -> None:
        r = await client.get("/api/v1/public/chat/%27or%201=1/config")
        assert r.status_code == 404
        # retour ligne en fin de slug
        biz = await _salon()
        r = await client.get(f"/api/v1/public/chat/{biz.slug}%0A/config")
        assert r.status_code == 404
        r = await client.post(
            f"/api/v1/public/chat/{'x' * 300}",
            json={"visitor_id": _visitor(), "message": "Bonjour"},
        )
        assert r.status_code == 404


class TestConfig:
    async def test_config_minimal(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        r = await client.get(f"/api/v1/public/chat/{biz.slug}/config")
        assert r.status_code == 200
        data = r.json()
        assert set(data) == {"name", "color", "greeting", "suggestions"}
        assert data["name"] == "Salon Léa"
        assert data["color"] == "#FF7F6A"
        assert "assistante virtuelle" in data["greeting"]
        assert "secret-owner" not in r.text and "0611" not in r.text
        assert "max-age" in r.headers.get("cache-control", "")

    async def test_config_tutoiement_and_color(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon(persona={"tutoiement": True, "widget_color": "#112233"})
        data = (await client.get(f"/api/v1/public/chat/{biz.slug}/config")).json()
        assert data["color"] == "#112233"
        assert data["greeting"].startswith("Salut")
        assert "assistante virtuelle" in data["greeting"]

    async def test_bad_color_ignored(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon(persona={"widget_color": "red;}body{display:none"})
        data = (await client.get(f"/api/v1/public/chat/{biz.slug}/config")).json()
        assert data["color"] == "#FF7F6A"


class TestChat:
    async def test_stable_conversation_per_visitor(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        vid = _visitor()
        url = f"/api/v1/public/chat/{biz.slug}"
        r1 = await client.post(url, json={"visitor_id": vid, "message": "Bonjour !"})
        assert r1.status_code == 200, r1.text
        assert r1.json()["response"]
        r2 = await client.post(
            url, json={"visitor_id": vid, "message": "Je veux parler à un humain"}
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["handoff"] is True

        conv_id = conversation_id_for(biz.id, vid)
        async with async_session_factory() as s:
            convs = (
                (await s.execute(select(Conversation).where(Conversation.business_id == biz.id)))
                .scalars()
                .all()
            )
            assert [c.id for c in convs] == [conv_id]
            assert convs[0].channel == "widget"
            n = await s.scalar(
                select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
            )
            assert n == 4

        # autre visiteur, autre conversation
        r3 = await client.post(url, json={"visitor_id": _visitor(), "message": "Bonjour"})
        assert r3.status_code == 200
        async with async_session_factory() as s:
            total = await s.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.business_id == biz.id)
            )
            assert total == 2

    async def test_no_leak(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            json={"visitor_id": _visitor(), "message": "Bonjour"},
        )
        assert r.status_code == 200
        data = r.json()
        assert set(data) == _PUBLIC_KEYS
        for secret in (str(biz.id), "secret-owner@lea.fr", "+33611223344", "intent", "entities"):
            assert secret not in r.text

    async def test_same_visitor_other_salon_is_separate(self, db_tables) -> None:
        a, b = await _salon(), await _salon()
        vid = _visitor()
        assert conversation_id_for(a.id, vid) != conversation_id_for(b.id, vid)
        assert conversation_id_for(a.id, vid) == conversation_id_for(a.id, vid)


class TestValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {"visitor_id": "x" * 20, "message": ""},
            {"visitor_id": "x" * 20, "message": "    "},
            {"visitor_id": "x" * 20, "message": "\x00\x01"},
            {"visitor_id": "x" * 20, "message": "a" * 1001},
            {"visitor_id": "court", "message": "Bonjour"},
            {"visitor_id": "x" * 65, "message": "Bonjour"},
            {"visitor_id": "pas bon !!" * 3, "message": "Bonjour"},
            {"visitor_id": "x" * 20, "message": "Bonjour", "business_id": str(uuid4())},
            {"message": "Bonjour"},
        ],
    )
    async def test_rejects_bad_input(self, client: AsyncClient, db_tables, payload) -> None:
        biz = await _salon()
        r = await client.post(f"/api/v1/public/chat/{biz.slug}", json=payload)
        assert r.status_code == 422, payload

    async def test_body_too_big(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            content=b'{"visitor_id":"' + b"x" * 40_000 + b'"}',
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 413

    async def test_not_json(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        r = await client.post(f"/api/v1/public/chat/{biz.slug}", content=b"bonjour")
        assert r.status_code == 422

    async def test_control_chars_cleaned(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        vid = _visitor()
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            json={"visitor_id": vid, "message": "Bon\x00jour‮ !"},
        )
        assert r.status_code == 200
        async with async_session_factory() as s:
            texts = (
                (
                    await s.execute(
                        select(Message.content_text).where(
                            Message.conversation_id == conversation_id_for(biz.id, vid),
                            Message.direction == "inbound",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert texts == ["Bonjour !"]


class TestRateLimit:
    async def test_visitor_limit(self, client: AsyncClient, db_tables, monkeypatch) -> None:
        monkeypatch.setattr(public_chat._VISITOR, "limit", 2)
        biz = await _salon()
        vid = _visitor()
        url = f"/api/v1/public/chat/{biz.slug}"
        for _ in range(2):
            ok = await client.post(url, json={"visitor_id": vid, "message": "Bonjour"})
            assert ok.status_code == 200
        r = await client.post(url, json={"visitor_id": vid, "message": "Bonjour"})
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert r.json()["retry_after"] >= 1
        # un autre visiteur passe
        other = await client.post(url, json={"visitor_id": _visitor(), "message": "Bonjour"})
        assert other.status_code == 200

    async def test_ip_limit(self, client: AsyncClient, db_tables, monkeypatch) -> None:
        monkeypatch.setattr(public_chat._IP, "limit", 2)
        biz = await _salon()
        url = f"/api/v1/public/chat/{biz.slug}"
        head = {"x-forwarded-for": "203.0.113.9"}
        for _ in range(2):
            r = await client.post(
                url, json={"visitor_id": _visitor(), "message": "Bonjour"}, headers=head
            )
            assert r.status_code == 200
        r = await client.post(
            url, json={"visitor_id": _visitor(), "message": "Bonjour"}, headers=head
        )
        assert r.status_code == 429
        # autre ip ok
        r = await client.post(
            url,
            json={"visitor_id": _visitor(), "message": "Bonjour"},
            headers={"x-forwarded-for": "198.51.100.7"},
        )
        assert r.status_code == 200

    async def test_salon_budget(self, client: AsyncClient, db_tables, monkeypatch) -> None:
        monkeypatch.setattr(public_chat._SALON, "limit", 1)
        # sans réserve
        monkeypatch.setattr(public_chat._SPARE, "limit", 0)
        biz = await _salon()
        url = f"/api/v1/public/chat/{biz.slug}"
        assert (
            await client.post(url, json={"visitor_id": _visitor(), "message": "Bonjour"})
        ).status_code == 200
        r = await client.post(url, json={"visitor_id": _visitor(), "message": "Bonjour"})
        assert r.status_code == 429

    async def test_one_message_at_a_time(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        vid = _visitor()
        public_chat._BUSY.add(conversation_id_for(biz.id, vid))
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}", json={"visitor_id": vid, "message": "Bonjour"}
        )
        assert r.status_code == 429

    async def test_window_is_bounded(self) -> None:
        w = public_chat._Window(3, 60, max_keys=50)
        for i in range(500):
            w.add(f"k{i}", 1.0)
        assert len(w._hits) == 50
        assert w.wait("k499", 2.0) == 0
        w.add("k499", 2.0)
        w.add("k499", 2.0)
        assert w.wait("k499", 3.0) > 0
        assert w.wait("k499", 70.0) == 0


class TestHumanTakeover:
    async def test_jenny_stays_quiet_and_poll_returns_team(
        self, client: AsyncClient, db_tables
    ) -> None:
        biz = await _salon()
        vid = _visitor()
        url = f"/api/v1/public/chat/{biz.slug}"
        assert (
            await client.post(url, json={"visitor_id": vid, "message": "Bonjour"})
        ).status_code == 200
        conv_id = conversation_id_for(biz.id, vid)
        now = datetime.now(UTC)
        async with async_session_factory() as s, s.begin():
            conv = await s.get(Conversation, conv_id)
            conv.assigned_to = "boss@lea.fr"
            s.add(
                Message(
                    conversation_id=conv_id,
                    business_id=biz.id,
                    external_message_id=str(uuid4()),
                    channel="widget",
                    direction="outbound",
                    sender_name="boss@lea.fr",
                    content_text="Bonjour, ici Léa, je prends le relais !",
                    status="failed",
                    received_at=now,
                    source_created_at=now,
                )
            )

        r = await client.post(url, json={"visitor_id": vid, "message": "Super merci"})
        assert r.status_code == 200
        data = r.json()
        assert data["human"] is True and data["response"] == ""

        p = await client.post(f"{url}/poll", json={"visitor_id": vid})
        assert p.status_code == 200
        body = p.json()
        assert body["human"] is True
        assert [m["text"] for m in body["messages"]] == ["Bonjour, ici Léa, je prends le relais !"]
        assert "boss@lea.fr" not in p.text

        async with async_session_factory() as s:
            inbound = await s.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conv_id, Message.direction == "inbound")
            )
            jenny = await s.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conv_id, Message.sender_name == "Jenny")
            )
        assert inbound == 2
        assert jenny == 1

    async def test_poll_other_visitor_sees_nothing(self, client: AsyncClient, db_tables) -> None:
        biz = await _salon()
        vid = _visitor()
        url = f"/api/v1/public/chat/{biz.slug}"
        await client.post(url, json={"visitor_id": vid, "message": "Bonjour"})
        p = await client.post(f"{url}/poll", json={"visitor_id": _visitor()})
        assert p.status_code == 200
        assert p.json() == {"human": False, "messages": []}


class TestProdAuth:
    async def test_public_even_with_auth_required(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "require_auth", True)
        biz = await _salon()
        assert (await client.get(f"/api/v1/public/chat/{biz.slug}/config")).status_code == 200
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            json={"visitor_id": _visitor(), "message": "Bonjour"},
        )
        assert r.status_code == 200, r.text
        # le reste reste protégé
        assert (await client.get("/api/v1/business/me")).status_code == 401
