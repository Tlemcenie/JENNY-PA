"""Widget : limiteur anti-blocage et accès anonyme."""

from __future__ import annotations

import random
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles
from starlette.requests import Request

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.api.routes import public_chat
from jenny.api.routes.public_chat import conversation_id_for
from jenny.core.config import get_settings
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.engine.factory import get_engine

ATTACKER = "203.0.113.66"
LEGIT = "198.51.100.7"


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


async def _salon() -> Business:
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon Léa", slug=f"lea-{uuid4().hex[:6]}")
        s.add(biz)
    return biz


def _visitor() -> str:
    return uuid4().hex


def _via_proxy(real_ip: str) -> dict[str, str]:
    """XFF forgé + hop ajouté par le proxy."""
    fake = ".".join(str(random.randint(1, 254)) for _ in range(4))
    return {"x-forwarded-for": f"{fake}, {real_ip}"}


async def _say(client, slug, vid, ip, text="Bonjour"):
    return await client.post(
        f"/api/v1/public/chat/{slug}",
        json={"visitor_id": vid, "message": text},
        headers=_via_proxy(ip),
    )


def _req(xff: str | None = None, host: str = "10.9.9.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


class TestClientIp:
    def test_spoofed_first_hop_ignored(self) -> None:
        assert public_chat._ip(_req(f"6.6.6.6, {LEGIT}")) == LEGIT
        assert public_chat._ip(_req(f"1.2.3.4, 5.6.7.8, {LEGIT}")) == LEGIT

    def test_more_proxies(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "rate_limit_proxy_hops", 2)
        assert public_chat._ip(_req(f"6.6.6.6, {LEGIT}, 10.0.0.1")) == LEGIT

    def test_no_proxy(self, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "rate_limit_proxy_hops", 0)
        assert public_chat._ip(_req("6.6.6.6", host=LEGIT)) == LEGIT

    def test_ipv6_grouped_by_64(self) -> None:
        a = public_chat._ip(_req("2001:db8:1:2:aaaa::1"))
        b = public_chat._ip(_req("2001:db8:1:2:bbbb::9"))
        c = public_chat._ip(_req("2001:db8:1:3::1"))
        assert a == b == "2001:db8:1:2::/64"
        assert c != a
        assert public_chat._ip(_req("::ffff:203.0.113.5")) == "203.0.113.5"
        assert public_chat._ip(_req("pas-une-ip")) == "pas-une-ip"


class TestWindow:
    def test_zero_limit_blocks(self) -> None:
        w = public_chat._Window(0, 60)
        assert w.wait("k", 1.0) > 0

    def test_used_drops_old(self) -> None:
        w = public_chat._Window(5, 10)
        w.add("k", 1.0)
        w.add("k", 2.0)
        assert w.used("k", 5.0) == 2
        assert w.used("k", 11.5) == 1
        assert w.used("absent", 1.0) == 0


class TestAttack:
    async def test_random_visitor_and_xff_keep_salon_open(
        self, client: AsyncClient, db_tables
    ) -> None:
        """Script : visitor_id et XFF aléatoires."""
        biz = await _salon()
        codes = [
            (await _say(client, biz.slug, _visitor(), ATTACKER)).status_code for _ in range(12)
        ]
        assert codes.count(200) == public_chat._NEW_IP.limit
        assert codes[-1] == 429
        last = await _say(client, biz.slug, _visitor(), ATTACKER)
        assert "nouvelles conversations" in last.json()["detail"]

        # le vrai client passe
        r = await _say(client, biz.slug, _visitor(), LEGIT)
        assert r.status_code == 200, r.text
        assert r.json()["response"]

        # inbox pas inondée
        async with async_session_factory() as s:
            n = await s.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.business_id == biz.id)
            )
        assert n == public_chat._NEW_IP.limit + 1

    async def test_one_ip_cannot_drain_salon(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        monkeypatch.setattr(public_chat._SALON, "limit", 8)
        monkeypatch.setattr(public_chat._SALON_IP, "limit", 3)
        biz = await _salon()
        vid = _visitor()
        codes = [(await _say(client, biz.slug, vid, ATTACKER)).status_code for _ in range(6)]
        assert codes == [200, 200, 200, 429, 429, 429]
        now = time.monotonic()
        assert public_chat._SALON.used(str(biz.id), now) == 3
        r = await _say(client, biz.slug, _visitor(), LEGIT)
        assert r.status_code == 200

    async def test_many_ips_then_reserve_for_ongoing(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        monkeypatch.setattr(public_chat._SALON, "limit", 4)
        monkeypatch.setattr(public_chat._SPARE, "limit", 4)
        monkeypatch.setattr(public_chat._SPARE_IP, "limit", 1)
        biz = await _salon()
        # client en cours de RDV
        legit = _visitor()
        assert (await _say(client, biz.slug, legit, LEGIT)).status_code == 200

        # 3 IP remplissent le salon
        bots = [f"203.0.113.{i}" for i in range(10, 16)]
        for ip in bots[:3]:
            assert (await _say(client, biz.slug, _visitor(), ip)).status_code == 200
        # nouvelles convs : moitié de réserve
        assert (await _say(client, biz.slug, _visitor(), bots[3])).status_code == 200
        assert (await _say(client, biz.slug, _visitor(), bots[4])).status_code == 200
        r = await _say(client, biz.slug, _visitor(), bots[5])
        assert r.status_code == 429
        assert "beaucoup de messages" in r.json()["detail"]

        # la conv en cours continue
        r = await _say(client, biz.slug, legit, LEGIT, "Demain 10h")
        assert r.status_code == 200, r.text
        # une IP ne vide pas la réserve
        again = await _say(client, biz.slug, _visitor(), bots[3])
        assert again.status_code == 429


class TestSharedLimit:
    async def test_calls_shared_limit_and_falls_back(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        calls: list[str] = []
        full = {"on": False}

        async def fake_limit(business_id) -> None:
            calls.append(str(business_id))
            if full["on"]:
                raise HTTPException(429, "Trop de requêtes")

        monkeypatch.setattr(public_chat, "enforce_business_chat_limit", fake_limit)
        biz = await _salon()
        assert (await _say(client, biz.slug, _visitor(), LEGIT)).status_code == 200
        assert calls == [str(biz.id)]

        # chat principal saturé
        full["on"] = True
        r = await _say(client, biz.slug, _visitor(), "198.51.100.8")
        assert r.status_code == 200, r.text
        assert public_chat._SPARE.used(str(biz.id), time.monotonic()) == 1


class TestStates:
    async def test_engine_states_are_bounded(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        """Éviction publique, mémoire seule."""
        monkeypatch.setattr(public_chat, "MAX_STATES", 2)
        sm = get_engine().state_manager
        evicted: list = []
        deleted: list = []

        def evict(conv_id) -> None:
            evicted.append(conv_id)
            sm._states.pop(str(conv_id), None)

        async def adelete(conv_id) -> None:
            deleted.append(conv_id)

        monkeypatch.setattr(sm, public_chat.EVICT_METHOD, evict, raising=False)
        monkeypatch.setattr(sm, "adelete", adelete)
        biz = await _salon()
        vids = [_visitor() for _ in range(3)]
        for i, vid in enumerate(vids):
            assert (await _say(client, biz.slug, vid, f"198.51.100.{20 + i}")).status_code == 200
        first, *rest = [conversation_id_for(biz.id, v) for v in vids]
        assert evicted == [first]
        assert sm.get(first) is None
        assert all(sm.get(c) is not None for c in rest)
        assert len(public_chat._STATES) == 2
        # copie Redis jamais effacée
        assert deleted == []

    async def test_no_public_evict_keeps_states(
        self, client: AsyncClient, db_tables, monkeypatch
    ) -> None:
        """Sans méthode publique : TTL du moteur."""
        monkeypatch.setattr(public_chat, "EVICT_METHOD", "pas_de_methode")
        monkeypatch.setattr(public_chat, "MAX_STATES", 1)
        biz = await _salon()
        old, new = _visitor(), _visitor()
        assert (await _say(client, biz.slug, old, LEGIT)).status_code == 200
        assert (await _say(client, biz.slug, new, "198.51.100.30")).status_code == 200
        old_id = conversation_id_for(biz.id, old)
        assert get_engine().state_manager.get(old_id) is not None
        assert not public_chat._STATES

    async def test_limiter_memory_bounded(self, db_tables) -> None:
        w = public_chat._Window(3, 60, max_keys=10)
        for i in range(200):
            public_chat._take([(w, f"ip{i % 30}")])
        assert len(w._hits) <= 10
        assert all(len(dq) <= 3 for dq in w._hits.values())


class TestAnonymous:
    async def test_dashboard_token_of_other_salon_ignored(
        self, client: AsyncClient, db_tables
    ) -> None:
        biz, other = await _salon(), await _salon()
        tok = create_access_token(uuid4(), "boss@ailleurs.fr", [other.id])
        r = await client.post(
            f"/api/v1/public/chat/{biz.slug}",
            json={"visitor_id": _visitor(), "message": "Bonjour"},
            headers={"Authorization": f"Bearer {tok}", **_via_proxy(LEGIT)},
        )
        assert r.status_code == 200, r.text

    async def test_linked_customer_keeps_chatting(self, client: AsyncClient, db_tables) -> None:
        """Conv rattachée à son client : ça continue."""
        biz = await _salon()
        vid = _visitor()
        assert (await _say(client, biz.slug, vid, LEGIT)).status_code == 200
        conv_id = conversation_id_for(biz.id, vid)
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name="Marie Dupont")
            s.add(cust)
            await s.flush()
            conv = await s.get(Conversation, conv_id)
            conv.customer_id = cust.id
        r = await _say(client, biz.slug, vid, LEGIT, "Merci !")
        assert r.status_code == 200, r.text
        # le moteur a reçu ce client
        async with async_session_factory() as s:
            owner = await s.scalar(
                select(Message.customer_id).where(
                    Message.conversation_id == conv_id,
                    Message.direction == "inbound",
                    Message.content_text == "Merci !",
                )
            )
        assert owner == cust.id

    async def test_other_channel_conv_not_resumed(self, client: AsyncClient, db_tables) -> None:
        """Conv d'un autre canal : refusée."""
        biz = await _salon()
        vid = _visitor()
        conv_id = conversation_id_for(biz.id, vid)
        async with async_session_factory() as s, s.begin():
            cust = Customer(business_id=biz.id, full_name="Paul Martin", phone="+33600000001")
            s.add(cust)
            await s.flush()
            s.add(
                Conversation(
                    id=conv_id,
                    business_id=biz.id,
                    customer_id=cust.id,
                    channel="whatsapp",
                    status="open",
                    message_count=0,
                )
            )
        r = await _say(client, biz.slug, vid, LEGIT)
        assert r.status_code == 403
        assert "Paul" not in r.text and "0600000001" not in r.text
