"""Tests : feedback 👍/👎 sur les réponses de Jenny.

Couvre les trois routes (`POST /feedback`, `GET /feedback/message/{id}`,
`GET /feedback/metrics`) sur SQLite réel : enregistrement, upsert, validation,
isolation multi-tenant, et l'agrégation des métriques de satisfaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import jenny.domain.models  # noqa: F401
from jenny.api.auth.jwt_utils import create_access_token
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.message import Message


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


async def _seed_conversation_with_reply(
    *, question: str = "Vous êtes ouverts samedi ?", answer: str = "Oui, de 9h à 17h !"
) -> tuple[Business, Message, Message]:
    """Crée business + conversation + un échange question (inbound) / réponse (outbound)."""
    now = datetime.now(UTC)
    async with async_session_factory() as s, s.begin():
        biz = Business(id=uuid4(), name="Salon", slug=f"s-{uuid4().hex[:6]}")
        s.add(biz)
        conv = Conversation(id=uuid4(), business_id=biz.id, channel="whatsapp")
        s.add(conv)
        inbound = Message(
            id=uuid4(),
            conversation_id=conv.id,
            business_id=biz.id,
            external_message_id=f"in-{uuid4().hex[:8]}",
            channel="whatsapp",
            direction="inbound",
            content_text=question,
            received_at=now - timedelta(seconds=30),
        )
        outbound = Message(
            id=uuid4(),
            conversation_id=conv.id,
            business_id=biz.id,
            external_message_id=f"out-{uuid4().hex[:8]}",
            channel="whatsapp",
            direction="outbound",
            content_text=answer,
            received_at=now,
        )
        s.add_all([inbound, outbound])
    return biz, inbound, outbound


def _auth(biz: Business) -> dict[str, str]:
    token = create_access_token(uuid4(), "gerant@test.fr", [biz.id])
    return {"Authorization": f"Bearer {token}"}


class TestSubmitFeedback:
    async def test_thumbs_up_persists(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": 1},
            headers=_auth(biz),
        )
        assert r.status_code == 200
        assert r.json() == {"message_id": str(reply.id), "rating": 1, "comment": None}

    async def test_upsert_replaces_rating_and_comment(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        headers = _auth(biz)
        await client.post(
            "/api/v1/feedback", json={"message_id": str(reply.id), "rating": 1}, headers=headers
        )
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": -1, "comment": "Horaires faux"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["rating"] == -1
        # Un seul avis par message : les métriques ne comptent qu'une évaluation.
        m = (await client.get("/api/v1/feedback/metrics", headers=headers)).json()
        assert m["total_rated"] == 1
        assert m["negative"] == 1

    async def test_recliking_thumb_keeps_comment(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        headers = _auth(biz)
        await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": -1, "comment": "le prix est faux"},
            headers=headers,
        )
        # Re-clic sans texte : le rating change, le commentaire saisi reste.
        r = await client.post(
            "/api/v1/feedback", json={"message_id": str(reply.id), "rating": 1}, headers=headers
        )
        assert r.status_code == 200
        assert r.json() == {
            "message_id": str(reply.id),
            "rating": 1,
            "comment": "le prix est faux",
        }

    async def test_rating_must_be_plus_or_minus_one(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": 0},
            headers=_auth(biz),
        )
        assert r.status_code == 422

    async def test_unknown_message_404(self, db_tables, client: AsyncClient) -> None:
        biz, _, _ = await _seed_conversation_with_reply()
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(uuid4()), "rating": 1},
            headers=_auth(biz),
        )
        assert r.status_code == 404

    async def test_other_business_message_forbidden(self, db_tables, client: AsyncClient) -> None:
        _, _, reply = await _seed_conversation_with_reply()
        other, _, _ = await _seed_conversation_with_reply()
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": 1},
            headers=_auth(other),
        )
        assert r.status_code == 403

    async def test_principal_without_business_forbidden(
        self, db_tables, client: AsyncClient
    ) -> None:
        _, _, reply = await _seed_conversation_with_reply()
        token = create_access_token(uuid4(), "sans-business@test.fr", [])
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    async def test_inbound_message_not_ratable(self, db_tables, client: AsyncClient) -> None:
        biz, inbound, _ = await _seed_conversation_with_reply()
        r = await client.post(
            "/api/v1/feedback",
            json={"message_id": str(inbound.id), "rating": 1},
            headers=_auth(biz),
        )
        assert r.status_code == 422

    async def test_requires_auth(self, db_tables, client: AsyncClient) -> None:
        _, _, reply = await _seed_conversation_with_reply()
        r = await client.post("/api/v1/feedback", json={"message_id": str(reply.id), "rating": 1})
        assert r.status_code == 401


class TestGetMessageFeedback:
    async def test_hydrates_existing_rating(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        headers = _auth(biz)
        await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": -1, "comment": "à revoir"},
            headers=headers,
        )
        r = await client.get(f"/api/v1/feedback/message/{reply.id}", headers=headers)
        assert r.status_code == 200
        assert r.json() == {"message_id": str(reply.id), "rating": -1, "comment": "à revoir"}

    async def test_unrated_returns_none(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        r = await client.get(f"/api/v1/feedback/message/{reply.id}", headers=_auth(biz))
        assert r.status_code == 200
        assert r.json()["rating"] is None

    async def test_other_business_sees_nothing(self, db_tables, client: AsyncClient) -> None:
        biz, _, reply = await _seed_conversation_with_reply()
        other, _, _ = await _seed_conversation_with_reply()
        await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": 1},
            headers=_auth(biz),
        )
        r = await client.get(f"/api/v1/feedback/message/{reply.id}", headers=_auth(other))
        # Isolation : l'avis existe mais reste invisible hors du business.
        assert r.json()["rating"] is None


class TestFeedbackMetrics:
    async def test_aggregates_and_context(self, db_tables, client: AsyncClient) -> None:
        biz, _, good = await _seed_conversation_with_reply()
        headers = _auth(biz)
        # Deuxième échange du MÊME business, jugé « à revoir » avec commentaire.
        async with async_session_factory() as s, s.begin():
            conv = Conversation(id=uuid4(), business_id=biz.id, channel="whatsapp")
            s.add(conv)
            now = datetime.now(UTC)
            q = Message(
                id=uuid4(),
                conversation_id=conv.id,
                business_id=biz.id,
                external_message_id=f"in-{uuid4().hex[:8]}",
                channel="whatsapp",
                direction="inbound",
                content_text="Combien pour un balayage ?",
                received_at=now - timedelta(seconds=10),
            )
            bad = Message(
                id=uuid4(),
                conversation_id=conv.id,
                business_id=biz.id,
                external_message_id=f"out-{uuid4().hex[:8]}",
                channel="whatsapp",
                direction="outbound",
                content_text="Je ne sais pas.",
                received_at=now,
            )
            s.add_all([q, bad])
        await client.post(
            "/api/v1/feedback", json={"message_id": str(good.id), "rating": 1}, headers=headers
        )
        await client.post(
            "/api/v1/feedback",
            json={"message_id": str(bad.id), "rating": -1, "comment": "Réponse inutile"},
            headers=headers,
        )

        m = (await client.get("/api/v1/feedback/metrics", headers=headers)).json()
        assert m["total_rated"] == 2
        assert m["positive"] == 1
        assert m["negative"] == 1
        assert m["satisfaction_pct"] == 50.0
        assert m["responses_total"] == 2  # seules les réponses outbound comptent
        assert m["last_7_days"] == {"positive": 1, "negative": 1}
        # Le 👎 est actionnable : question du client + réponse + commentaire.
        assert len(m["recent_comments"]) == 1
        rc = m["recent_comments"][0]
        assert rc["comment"] == "Réponse inutile"
        assert rc["question"] == "Combien pour un balayage ?"
        assert rc["answer"] == "Je ne sais pas."

    async def test_empty_state(self, db_tables, client: AsyncClient) -> None:
        biz, _, _ = await _seed_conversation_with_reply()
        m = (await client.get("/api/v1/feedback/metrics", headers=_auth(biz))).json()
        assert m["total_rated"] == 0
        assert m["satisfaction_pct"] == 0.0
        assert m["recent_comments"] == []
        assert m["recent_positive"] == []

    async def test_recent_positive_surfaced(self, db_tables, client: AsyncClient) -> None:
        # « Ce qui marche » : un 👍 remonte avec le contexte question/réponse.
        biz, _, reply = await _seed_conversation_with_reply(
            question="Vous êtes ouverts samedi ?", answer="Oui, de 9h à 17h !"
        )
        await client.post(
            "/api/v1/feedback", json={"message_id": str(reply.id), "rating": 1}, headers=_auth(biz)
        )
        m = (await client.get("/api/v1/feedback/metrics", headers=_auth(biz))).json()
        assert len(m["recent_positive"]) == 1
        rp = m["recent_positive"][0]
        assert rp["answer"] == "Oui, de 9h à 17h !"
        assert rp["question"] == "Vous êtes ouverts samedi ?"


class TestNegativeFeedbackNotification:
    async def test_negative_creates_owner_notification(
        self, db_tables, client: AsyncClient
    ) -> None:
        from jenny.domain.models.notification import Notification

        biz, _, reply = await _seed_conversation_with_reply()
        await client.post(
            "/api/v1/feedback",
            json={"message_id": str(reply.id), "rating": -1, "comment": "à revoir"},
            headers=_auth(biz),
        )
        async with async_session_factory() as s:
            notifs = (
                (await s.execute(select(Notification).where(Notification.business_id == biz.id)))
                .scalars()
                .all()
            )
        feedback_notifs = [n for n in notifs if n.kind == "feedback_negative"]
        assert len(feedback_notifs) == 1
        assert "revoir" in (feedback_notifs[0].body or "")

    async def test_positive_creates_no_notification(self, db_tables, client: AsyncClient) -> None:
        from jenny.domain.models.notification import Notification

        biz, _, reply = await _seed_conversation_with_reply()
        await client.post(
            "/api/v1/feedback", json={"message_id": str(reply.id), "rating": 1}, headers=_auth(biz)
        )
        async with async_session_factory() as s:
            n = await s.scalar(
                select(Notification).where(
                    Notification.business_id == biz.id,
                    Notification.kind == "feedback_negative",
                )
            )
        assert n is None
