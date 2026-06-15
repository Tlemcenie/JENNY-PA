"""Tests e2e du 2e lot back : priorité, bulk, fusion, recherche, notifications,
audit, clés API, SLA fins (#1, #4, #5, #7, #8, #10, #14, #15, #16, #17).

Réutilise le schéma SQLite de test (fixture ``db_tables``) et l'auth réelle.
Les conversations sont semées via l'ingestion formulaire (chemin DB complet).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401 — enregistre les modèles dans Base.metadata
from jenny.api.main import create_app
from jenny.api.routes.conversations import resolve_sla_minutes
from jenny.db.base import Base
from jenny.db.session import engine
from jenny.domain.models.business import Business

_PASSWORD = "Strong#1234"

# Compteur pour rendre chaque soumission de formulaire unique (la dédup
# d'ingestion se base sur form_id + submitted_at).
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
    """Inscrit + vérifie un compte, renvoie (headers, business_id)."""
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
    """Crée une conversation via l'ingestion formulaire, renvoie son id."""
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


# ── #4 Priorité ──────────────────────────────────────────────────────────────


class TestPriority:
    @pytest.mark.asyncio
    async def test_set_priority_and_filter_and_sort(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "prio@x.com")
        cid = await _seed_conversation(
            client, bid, email="c1@x.com", message="Bonjour, une question."
        )

        # PATCH priorité.
        r = await client.patch(
            f"/api/v1/conversations/{cid}/priority",
            json={"priority_level": "critical"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["priority_level"] == "critical"

        # Le détail et la liste exposent la priorité.
        detail = (
            await client.get(f"/api/v1/conversations/{cid}", headers=headers)
        ).json()
        assert detail["priority_level"] == "critical"

        # Filtre par priorité.
        filtered = (
            await client.get(
                "/api/v1/conversations?priority=critical", headers=headers
            )
        ).json()
        assert filtered["total"] == 1
        # Filtre qui ne matche pas.
        none = (
            await client.get("/api/v1/conversations?priority=low", headers=headers)
        ).json()
        assert none["total"] == 0

        # Tri par priorité accepté.
        sorted_resp = await client.get(
            "/api/v1/conversations?sort_by=priority", headers=headers
        )
        assert sorted_resp.status_code == 200


# ── #1 Actions groupées ──────────────────────────────────────────────────────


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


# ── #10 Fusion ───────────────────────────────────────────────────────────────


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

        # La cible porte les 2 messages.
        detail = (
            await client.get(f"/api/v1/conversations/{target}", headers=headers)
        ).json()
        assert len(detail["messages"]) == 2

        # La source est archivée (absente de la vue active par défaut).
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


# ── #8 Recherche plein-texte ─────────────────────────────────────────────────


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


# ── #5/#14 Auto-escalade + notifications ─────────────────────────────────────


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

        # La conversation est escaladée et sa priorité remontée.
        detail = (
            await client.get(f"/api/v1/conversations/{cid}", headers=headers)
        ).json()
        assert detail["sentiment"] == "negative"
        assert detail["priority_level"] == "high"

        active = (await client.get("/api/v1/conversations", headers=headers)).json()
        conv = next(c for c in active["conversations"] if c["id"] == cid)
        assert conv["is_escalated"] is True
        assert "mécontent" in conv["tags"]

        # Une notification de diffusion (escalade) est créée et listée.
        notifs = (await client.get("/api/v1/notifications", headers=headers)).json()
        assert notifs["unread"] >= 1
        assert any(n["kind"] == "escalated" for n in notifs["notifications"])

        # Compteur non lues, puis tout marquer lu.
        cnt = (
            await client.get("/api/v1/notifications/unread-count", headers=headers)
        ).json()
        assert cnt["unread"] >= 1
        read = await client.post(
            "/api/v1/notifications/read-all", headers=headers
        )
        assert read.json()["unread"] == 0


# ── #15 Notification à l'agent assigné ───────────────────────────────────────


class TestAssigneeNotification:
    @pytest.mark.asyncio
    async def test_assign_to_member_notifies_member(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "owner@x.com")
        cid = await _seed_conversation(
            client, bid, email="c@x.com", message="Bonjour"
        )
        # Crée un coéquipier (compte + rattachement).
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

        # L'owner attribue la conversation au coéquipier.
        ra = await client.post(
            f"/api/v1/conversations/{cid}/assign",
            json={"assignee": member_email},
            headers=headers,
        )
        assert ra.status_code == 200, ra.text

        # Le coéquipier se connecte et voit la notification d'attribution.
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


# ── #16 Journal d'audit ──────────────────────────────────────────────────────


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


# ── #17 Clés API ─────────────────────────────────────────────────────────────


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
        assert "secret" not in listed[0]  # le secret n'est jamais re-listé
        assert listed[0]["scopes"] == ["read"]

        revoked = await client.delete(
            f"/api/v1/api-keys/{key_id}", headers=headers
        )
        assert revoked.status_code == 200
        again = (await client.get("/api/v1/api-keys", headers=headers)).json()
        assert again == []


# ── #7 SLA par priorité/canal ────────────────────────────────────────────────


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
        # Priorité haute → 5 (plus strict que 30).
        assert resolve_sla_minutes(biz, priority="high", channel="email") == 5
        # Canal whatsapp seul → 10.
        assert resolve_sla_minutes(biz, priority="medium", channel="whatsapp") == 10
        # Les deux → min(30, ... selon dispo) = 5.
        assert resolve_sla_minutes(biz, priority="high", channel="whatsapp") == 5
        # Aucune règle applicable → défaut business.
        assert resolve_sla_minutes(biz, priority="low", channel="email") == 30
