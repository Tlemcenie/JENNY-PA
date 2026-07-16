"""tests e2e du 2e lot."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.api.routes.conversations import resolve_sla_minutes
from jenny.db.base import Base
from jenny.db.session import engine
from jenny.domain.models.business import Business

_PASSWORD = "Strong#1234"

# compteur pour soumissions uniques
_SEQ = {"n": 0}


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://e2e"
    ) as c:
        yield c


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _auth(client: AsyncClient, email: str) -> tuple[dict, str]:
    """inscrit et connecte un compte."""
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Owner", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": code}
    )
    assert rv.status_code == 200, rv.text
    token = rv.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


async def _seed_conversation(
    client: AsyncClient, bid: str, *, email: str, message: str, name: str = "Client"
) -> str:
    """crée une conversation via formulaire."""
    _SEQ["n"] += 1
    submitted_at = f"2026-06-14T10:{_SEQ['n'] // 60:02d}:{_SEQ['n'] % 60:02d}Z"
    r = await client.post(
        f"/api/v1/ingest/form?business_id={bid}",
        json={
            "form_id": "contact",
            "submitted_at": submitted_at,
            "full_name": name,
            "email": email,
            "subject": "Sujet",
            "message": message,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["conversation_id"]


# priorité (#4)


class TestPriority:
    @pytest.mark.asyncio
    async def test_set_priority_and_filter_and_sort(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "prio@x.com")
        cid = await _seed_conversation(
            client, bid, email="c1@x.com", message="Bonjour, une question."
        )

        # patch priorité
        r = await client.patch(
            f"/api/v1/conversations/{cid}/priority",
            json={"priority_level": "critical"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["priority_level"] == "critical"

        # le détail l'expose
        detail = (
            await client.get(f"/api/v1/conversations/{cid}", headers=headers)
        ).json()
        assert detail["priority_level"] == "critical"

        # filtre par priorité
        filtered = (
            await client.get(
                "/api/v1/conversations?priority=critical", headers=headers
            )
        ).json()
        assert filtered["total"] == 1
        # filtre sans résultat
        none = (
            await client.get("/api/v1/conversations?priority=low", headers=headers)
        ).json()
        assert none["total"] == 0

        # tri par priorité ok
        sorted_resp = await client.get(
            "/api/v1/conversations?sort_by=priority", headers=headers
        )
        assert sorted_resp.status_code == 200


# actions groupées (#1)


class TestBulk:
    @pytest.mark.asyncio
    async def test_bulk_priority_and_tag(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "bulk@x.com")
        c1 = await _seed_conversation(client, bid, email="a@x.com", message="Salut")
        c2 = await _seed_conversation(client, bid, email="b@x.com", message="Coucou")

        r = await client.post(
            "/api/v1/conversations/bulk",
            json={"ids": [c1, c2], "action": "priority", "value": "high"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 2

        r2 = await client.post(
            "/api/v1/conversations/bulk",
            json={"ids": [c1, c2], "action": "tag_add", "value": "vip"},
            headers=headers,
        )
        assert r2.json()["updated"] == 2

        detail = (
            await client.get(f"/api/v1/conversations/{c1}", headers=headers)
        ).json()
        assert detail["priority_level"] == "high"
        assert "vip" in detail["tags"]

    @pytest.mark.asyncio
    async def test_bulk_invalid_priority_rejected(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "bulk2@x.com")
        c1 = await _seed_conversation(client, bid, email="a@x.com", message="Salut")
        r = await client.post(
            "/api/v1/conversations/bulk",
            json={"ids": [c1], "action": "priority", "value": "nope"},
            headers=headers,
        )
        assert r.status_code == 400


# fusion (#10)


class TestMerge:
    @pytest.mark.asyncio
    async def test_merge_moves_messages_and_archives_source(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "merge@x.com")
        target = await _seed_conversation(
            client, bid, email="t@x.com", message="Premier fil"
        )
        source = await _seed_conversation(
            client, bid, email="s@x.com", message="Second fil"
        )

        r = await client.post(
            f"/api/v1/conversations/{target}/merge",
            json={"source_id": source},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["merged_messages"] == 1
        assert body["message_count"] == 2

        # cible : 2 messages
        detail = (
            await client.get(f"/api/v1/conversations/{target}", headers=headers)
        ).json()
        assert len(detail["messages"]) == 2

        # source archivée
        active = (await client.get("/api/v1/conversations", headers=headers)).json()
        ids = {c["id"] for c in active["conversations"]}
        assert source not in ids
        assert target in ids

    @pytest.mark.asyncio
    async def test_merge_self_rejected(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "merge2@x.com")
        cid = await _seed_conversation(client, bid, email="x@x.com", message="Hi")
        r = await client.post(
            f"/api/v1/conversations/{cid}/merge",
            json={"source_id": cid},
            headers=headers,
        )
        assert r.status_code == 400


# recherche plein-texte (#8)


class TestMessageSearch:
    @pytest.mark.asyncio
    async def test_search_finds_message(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "search@x.com")
        await _seed_conversation(
            client,
            bid,
            email="c@x.com",
            message="Je voudrais un devis pour une prestation.",
        )
        r = await client.get(
            "/api/v1/conversations/search/messages?q=devis", headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        assert any("devis" in h["snippet"].lower() for h in body["hits"])

    @pytest.mark.asyncio
    async def test_search_no_match(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "search2@x.com")
        await _seed_conversation(client, bid, email="c@x.com", message="Bonjour")
        r = await client.get(
            "/api/v1/conversations/search/messages?q=zzzqqq", headers=headers
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0


# escalade + notifs (#5/#14)


class TestEscalationAndNotifications:
    @pytest.mark.asyncio
    async def test_negative_message_escalates_and_notifies(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "esc@x.com")
        cid = await _seed_conversation(
            client,
            bid,
            email="angry@x.com",
            message="C'est inadmissible et scandaleux, remboursez-moi immédiatement !",
        )

        # escaladée + priorité haute
        detail = (
            await client.get(f"/api/v1/conversations/{cid}", headers=headers)
        ).json()
        assert detail["sentiment"] == "negative"
        assert detail["priority_level"] == "high"

        active = (await client.get("/api/v1/conversations", headers=headers)).json()
        conv = next(c for c in active["conversations"] if c["id"] == cid)
        assert conv["is_escalated"] is True
        assert "mécontent" in conv["tags"]

        # notif escalade créée
        notifs = (await client.get("/api/v1/notifications", headers=headers)).json()
        assert notifs["unread"] >= 1
        assert any(n["kind"] == "escalated" for n in notifs["notifications"])

        # compteur puis tout lu
        cnt = (
            await client.get("/api/v1/notifications/unread-count", headers=headers)
        ).json()
        assert cnt["unread"] >= 1
        read = await client.post(
            "/api/v1/notifications/read-all", headers=headers
        )
        assert read.json()["unread"] == 0


# notif agent assigné (#15)


class TestAssigneeNotification:
    @pytest.mark.asyncio
    async def test_assign_to_member_notifies_member(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "owner@x.com")
        cid = await _seed_conversation(
            client, bid, email="c@x.com", message="Bonjour"
        )
        # crée un coéquipier
        member_email = "agent@x.com"
        rm = await client.post(
            "/api/v1/business/members",
            json={
                "email": member_email,
                "full_name": "Agent",
                "password": _PASSWORD,
                "role": "agent",
            },
            headers=headers,
        )
        assert rm.status_code == 201, rm.text

        # l'owner lui attribue
        ra = await client.post(
            f"/api/v1/conversations/{cid}/assign",
            json={"assignee": member_email},
            headers=headers,
        )
        assert ra.status_code == 200, ra.text

        # le coéquipier voit la notif
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": member_email, "password": _PASSWORD},
        )
        assert login.status_code == 200, login.text
        mtoken = login.json()["access_token"]
        mheaders = {"Authorization": f"Bearer {mtoken}"}
        notifs = (
            await client.get("/api/v1/notifications", headers=mheaders)
        ).json()
        assert any(n["kind"] == "assigned" for n in notifs["notifications"])


# journal d'audit (#16)


class TestAudit:
    @pytest.mark.asyncio
    async def test_status_change_is_audited(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "audit@x.com")
        cid = await _seed_conversation(client, bid, email="c@x.com", message="Hi")
        await client.patch(
            f"/api/v1/conversations/{cid}/status",
            json={"status": "closed"},
            headers=headers,
        )
        audit = (await client.get("/api/v1/audit", headers=headers)).json()
        assert audit["total"] >= 1
        actions = {a["action"] for a in audit["items"]}
        assert "conversation.status_changed" in actions


# clés API (#17)


class TestApiKeys:
    @pytest.mark.asyncio
    async def test_create_list_revoke(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, _bid = await _auth(client, "keys@x.com")

        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "CI", "scopes": ["read"]},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["secret"].startswith("sk_")
        assert len(body["key_prefix"]) == 16
        key_id = body["id"]

        listed = (await client.get("/api/v1/api-keys", headers=headers)).json()
        assert len(listed) == 1
        assert "secret" not in listed[0]  # secret jamais re-listé
        assert listed[0]["scopes"] == ["read"]

        revoked = await client.delete(
            f"/api/v1/api-keys/{key_id}", headers=headers
        )
        assert revoked.status_code == 200
        again = (await client.get("/api/v1/api-keys", headers=headers)).json()
        assert again == []


# SLA priorité/canal (#7)


class TestSlaRules:
    @pytest.mark.asyncio
    async def test_sla_rules_roundtrip(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, _bid = await _auth(client, "sla@x.com")
        r = await client.patch(
            "/api/v1/business/me",
            json={"sla_rules": {"priority": {"high": 5}, "channel": {"whatsapp": 10}}},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        me = (await client.get("/api/v1/business/me", headers=headers)).json()
        assert me["sla_rules"]["priority"]["high"] == 5

    def test_resolve_sla_minutes_picks_strictest(self) -> None:
        biz = Business(
            name="X",
            slug="x",
            sla_minutes=30,
            sla_rules={"priority": {"high": 5}, "channel": {"whatsapp": 10}},
        )
        # priorité haute → 5
        assert resolve_sla_minutes(biz, priority="high", channel="email") == 5
        # whatsapp seul → 10
        assert resolve_sla_minutes(biz, priority="medium", channel="whatsapp") == 10
        # les deux → 5
        assert resolve_sla_minutes(biz, priority="high", channel="whatsapp") == 5
        # sinon défaut business
        assert resolve_sla_minutes(biz, priority="low", channel="email") == 30
