"""Tests e2e : boucle d'apprentissage (lacunes de connaissance).

Vérifie qu'une question sans réponse est enregistrée (+ notification), qu'elle se
déduplique, et que le propriétaire peut la récapituler, y répondre et l'ignorer.
Sur schéma SQLite (sans Postgres/Ollama).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.knowledge_gap import KnowledgeGap
from jenny.domain.models.notification import Notification

_PASSWORD = "Strong#1234"


@compiles(ARRAY, "sqlite")
def _array_as_json_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as c:
        yield c


@pytest.fixture
async def db_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _auth(client: AsyncClient, email: str) -> tuple[dict, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "Boss", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    rv = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert rv.status_code == 200, rv.text
    headers = {"Authorization": f"Bearer {rv.json()['access_token']}"}
    bid = (await client.get("/api/v1/auth/me", headers=headers)).json()["business_id"]
    return headers, bid


async def _seed_gap(business_id: str, question: str, channel: str = "whatsapp") -> None:
    """Simule une réponse moteur avec lacune et persiste le signal."""
    from jenny.engine.conversation_engine import EngineResponse
    from jenny.services.learning_service import persist_engine_signals

    result = EngineResponse(
        response_text="Je vérifie ça et je reviens vers vous !",
        intent="faq",
        knowledge_gap=True,
        gap_question=question,
    )
    async with async_session_factory() as s:
        await persist_engine_signals(
            s,
            business_id=UUID(business_id),
            customer_id=None,
            conversation_id=None,
            channel=channel,
            result=result,
        )


class TestLearningLoop:
    @pytest.mark.asyncio
    async def test_gap_recorded_deduped_and_notified(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        _headers, bid = await _auth(client, "gap@x.com")

        # Même question (formulée différemment) → 1 seule lacune, occurrences=2.
        await _seed_gap(bid, "Vous êtes ouverts le dimanche ?")
        await _seed_gap(bid, "vous etes ouverts le dimanche")

        async with async_session_factory() as s:
            gaps = (
                await s.execute(select(KnowledgeGap).where(KnowledgeGap.business_id == UUID(bid)))
            ).scalars().all()
            assert len(gaps) == 1
            assert gaps[0].occurrences == 2
            # Une notification a été créée pour l'équipe.
            n = (
                await s.execute(
                    select(func.count(Notification.id)).where(
                        Notification.business_id == UUID(bid),
                        Notification.kind == "knowledge_gap",
                    )
                )
            ).scalar_one()
            assert n == 1

    @pytest.mark.asyncio
    async def test_list_recap_answer_dismiss(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "loop@x.com")
        await _seed_gap(bid, "Faites-vous des colorations végétales ?")
        await _seed_gap(bid, "Acceptez-vous les paiements en plusieurs fois ?")

        # Liste des lacunes ouvertes.
        listed = (await client.get("/api/v1/knowledge-gaps", headers=headers)).json()
        assert listed["total"] == 2
        gap_id = listed["gaps"][0]["id"]
        other_id = listed["gaps"][1]["id"]

        # Récapitulatif à présenter au propriétaire.
        recap = (await client.get("/api/v1/knowledge-gaps/recap", headers=headers)).json()
        assert recap["total_open"] == 2 and len(recap["questions"]) == 2
        assert "répondre" in recap["recap_text"].lower()

        # Stats.
        stats = (await client.get("/api/v1/knowledge-gaps/stats", headers=headers)).json()
        assert stats["open"] == 2

        # Répondre (sans enregistrement KB : pgvector indisponible sous SQLite).
        ans = await client.post(
            f"/api/v1/knowledge-gaps/{gap_id}/answer",
            headers=headers,
            json={"answer": "Oui, nous proposons des colorations 100% végétales.", "save_to_kb": False},
        )
        assert ans.status_code == 200, ans.text
        assert ans.json()["gap"]["status"] == "answered"

        # La lacune répondue n'est plus « ouverte ».
        still_open = (await client.get("/api/v1/knowledge-gaps?status=open", headers=headers)).json()
        assert still_open["total"] == 1

        # Ignorer l'autre.
        d = await client.post(f"/api/v1/knowledge-gaps/{other_id}/dismiss", headers=headers)
        assert d.status_code == 200 and d.json()["status"] == "dismissed"

        final = (await client.get("/api/v1/knowledge-gaps/stats", headers=headers)).json()
        assert final["open"] == 0 and final["answered"] == 1 and final["dismissed"] == 1

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client: AsyncClient, db_tables: None) -> None:
        _headers, bid = await _auth(client, "metrics@x.com")
        headers = _headers
        await _seed_gap(bid, "Une question de test sans réponse ?")
        m = (await client.get("/api/v1/jenny/metrics", headers=headers)).json()
        assert m["gaps"]["open"] >= 1
        assert "conversations" in m and "top_open_questions" in m
        assert any("test" in q.lower() for q in m["top_open_questions"])

    @pytest.mark.asyncio
    async def test_copilot_suggest(self, client: AsyncClient, db_tables: None) -> None:
        headers, _ = await _auth(client, "copilot@x.com")
        # Message de politesse → pas de RAG (greeting), réponse via le moteur.
        r = await client.post(
            "/api/v1/copilot/suggest",
            headers=headers,
            json={"message": "Bonjour, comment allez-vous ?"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data["suggestion"], str) and len(data["suggestion"]) > 0

    @pytest.mark.asyncio
    async def test_answer_save_to_kb_is_graceful_without_pgvector(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "kbsave@x.com")
        await _seed_gap(bid, "Quel est le prix d'une coupe homme ?")
        gid = (await client.get("/api/v1/knowledge-gaps", headers=headers)).json()["gaps"][0]["id"]
        # save_to_kb=True : la base vectorielle n'existe pas sous SQLite → la réponse
        # est conservée et l'API répond proprement (saved_to_kb=False), sans crash.
        r = await client.post(
            f"/api/v1/knowledge-gaps/{gid}/answer",
            headers=headers,
            json={"answer": "Une coupe homme est à 25 €.", "save_to_kb": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["gap"]["status"] == "answered"
        assert r.json()["saved_to_kb"] is False
