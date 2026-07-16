"""tests prestations + questions en attente."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

import jenny.domain.models  # noqa: F401
from jenny.api.main import create_app
from jenny.db.base import Base
from jenny.db.session import async_session_factory, engine
from jenny.domain.models.pending_question import PendingQuestion

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


class TestPrestations:
    @pytest.mark.asyncio
    async def test_crud(self, client: AsyncClient, db_tables: None) -> None:
        headers, _bid = await _auth(client, "presta-crud@x.com")

        # vide au départ
        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed == {"prestations": [], "total": 0}

        # création
        created = await client.post(
            "/api/v1/prestations",
            headers=headers,
            json={
                "name": "Coupe femme",
                "category": "coupe",
                "duration_minutes": 45,
                "price_cents": 3900,
                "description": "Shampoing + coupe + coiffage",
            },
        )
        assert created.status_code == 201, created.text
        presta = created.json()
        assert presta["name"] == "Coupe femme"
        assert presta["price_cents"] == 3900
        assert presta["price_eur"] == 39.0
        assert presta["is_active"] is True
        pid = presta["id"]

        # liste : 1 prestation
        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed["total"] == 1
        assert listed["prestations"][0]["id"] == pid

        # patch partiel
        patched = await client.patch(
            f"/api/v1/prestations/{pid}",
            headers=headers,
            json={"price_cents": 4200, "is_active": False},
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["price_cents"] == 4200
        assert body["price_eur"] == 42.0
        assert body["is_active"] is False
        # nom inchangé
        assert body["name"] == "Coupe femme"

        # inactives toujours listées
        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed["total"] == 1

        # suppression
        deleted = await client.delete(f"/api/v1/prestations/{pid}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"status": "deleted", "id": pid}

        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed["total"] == 0

    @pytest.mark.asyncio
    async def test_update_delete_other_business_is_404(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, _ = await _auth(client, "presta-owner@x.com")
        other_headers, _ = await _auth(client, "presta-intrus@x.com")
        created = await client.post(
            "/api/v1/prestations",
            headers=headers,
            json={"name": "Balayage", "category": "couleur", "price_cents": 8000},
        )
        pid = created.json()["id"]

        # autre business : 404
        assert (
            await client.patch(
                f"/api/v1/prestations/{pid}",
                headers=other_headers,
                json={"price_cents": 1},
            )
        ).status_code == 404
        assert (
            await client.delete(f"/api/v1/prestations/{pid}", headers=other_headers)
        ).status_code == 404

    @pytest.mark.asyncio
    async def test_seed_coiffeur_idempotent(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, _bid = await _auth(client, "presta-seed@x.com")

        # 1er appel : seed
        seeded = await client.post("/api/v1/prestations/seed-coiffeur", headers=headers)
        assert seeded.status_code == 200, seeded.text
        body = seeded.json()
        assert body["prestations"] == 7
        # pas de pgvector : 0 attendu
        assert body["knowledge"] >= 0

        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed["total"] == 7
        # trié par sort_order
        assert listed["prestations"][0]["name"] == "Coupe femme"

        # 2e appel : idempotent
        again = await client.post("/api/v1/prestations/seed-coiffeur", headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["prestations"] == 0
        listed = (await client.get("/api/v1/prestations", headers=headers)).json()
        assert listed["total"] == 7


async def _seed_pending(
    business_id: str,
    question: str,
    *,
    origin: str = "customer",
    conversation_id: UUID | None = None,
) -> str:
    """insère une question en attente."""
    async with async_session_factory() as s:
        pq = PendingQuestion(
            business_id=UUID(business_id),
            conversation_id=conversation_id,
            question=question,
            origin=origin,
            status="open",
        )
        s.add(pq)
        await s.commit()
        await s.refresh(pq)
        return str(pq.id)


class TestPendingQuestions:
    @pytest.mark.asyncio
    async def test_list_answer_dismiss(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "pending-loop@x.com")
        conv = uuid4()
        q1 = await _seed_pending(
            bid, "Faites-vous des chignons de mariée ?", conversation_id=conv
        )
        q2 = await _seed_pending(bid, "Avez-vous un parking ?", conversation_id=conv)

        # liste les ouvertes
        listed = (await client.get("/api/v1/pending-questions", headers=headers)).json()
        assert listed["total"] == 2
        ids = {item["id"] for item in listed["questions"]}
        assert ids == {q1, q2}

        # filtre par conversation
        by_conv = (
            await client.get(
                f"/api/v1/pending-questions?conversation_id={conv}", headers=headers
            )
        ).json()
        assert by_conv["total"] == 2
        assert by_conv["questions"][0]["conversation_id"] == str(conv)

        # répond sans KB
        ans = await client.post(
            f"/api/v1/pending-questions/{q1}/answer",
            headers=headers,
            json={"answer": "Oui, sur rendez-vous le matin.", "save_to_kb": False},
        )
        assert ans.status_code == 200, ans.text
        body = ans.json()
        assert body["status"] == "answered"
        assert body["answer"] == "Oui, sur rendez-vous le matin."

        # plus ouverte
        still_open = (
            await client.get("/api/v1/pending-questions?status=open", headers=headers)
        ).json()
        assert still_open["total"] == 1
        assert still_open["questions"][0]["id"] == q2

        # visible avec status=answered
        answered = (
            await client.get(
                "/api/v1/pending-questions?status=answered", headers=headers
            )
        ).json()
        assert answered["total"] == 1 and answered["questions"][0]["id"] == q1

        # dismiss la 2e
        d = await client.post(
            f"/api/v1/pending-questions/{q2}/dismiss", headers=headers
        )
        assert d.status_code == 200, d.text
        assert d.json()["status"] == "dismissed"

        # plus rien d'ouvert
        assert (
            await client.get("/api/v1/pending-questions?status=open", headers=headers)
        ).json()["total"] == 0
        assert (
            await client.get("/api/v1/pending-questions?status=all", headers=headers)
        ).json()["total"] == 2

    @pytest.mark.asyncio
    async def test_answer_save_to_kb_is_graceful_without_pgvector(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        headers, bid = await _auth(client, "pending-kbsave@x.com")
        qid = await _seed_pending(bid, "Quel est le prix d'une coloration ?")
        # pgvector absent : pas de crash
        r = await client.post(
            f"/api/v1/pending-questions/{qid}/answer",
            headers=headers,
            json={"answer": "Une coloration est à 55 €.", "save_to_kb": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "answered"

    @pytest.mark.asyncio
    async def test_answer_other_business_is_404(
        self, client: AsyncClient, db_tables: None
    ) -> None:
        _headers, bid = await _auth(client, "pending-owner@x.com")
        other_headers, _ = await _auth(client, "pending-intrus@x.com")
        qid = await _seed_pending(bid, "Question privée ?")
        assert (
            await client.post(
                f"/api/v1/pending-questions/{qid}/answer",
                headers=other_headers,
                json={"answer": "nope"},
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/pending-questions/{qid}/dismiss", headers=other_headers
            )
        ).status_code == 404
