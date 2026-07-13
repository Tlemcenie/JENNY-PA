"""Tests pour la route API de conversation."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from jenny.api.main import create_app


@pytest.fixture
async def client():
    """Client HTTP async pour les tests."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestConversationAPI:
    """Tests pour l'endpoint /api/v1/conversation/chat."""

    @pytest.mark.asyncio
    async def test_chat_greeting(self, client: AsyncClient) -> None:
        """Envoie un message de salutation."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Bonjour !",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert data["intent"] == "greeting"

    @pytest.mark.asyncio
    async def test_chat_order_status(self, client: AsyncClient) -> None:
        """Envoie une demande de suivi de commande."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Où en est ma commande CMD-12345 ?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "order_status"

    @pytest.mark.asyncio
    async def test_chat_escalation(self, client: AsyncClient) -> None:
        """Demande d'escalation vers un humain."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Je veux parler à un humain",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["requires_human"] is True

    @pytest.mark.asyncio
    async def test_chat_empty_message(self, client: AsyncClient) -> None:
        """Message vide → erreur 422."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_conversation_status_not_found(self, client: AsyncClient) -> None:
        """Conversation inexistante → not_found."""
        conv_id = str(uuid4())
        response = await client.get(
            f"/api/v1/conversation/status/{conv_id}",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_scoped_to_business(self, client: AsyncClient) -> None:
        """Isolation multi-tenant : le statut d'une conversation n'est visible que
        par son business (un token d'un AUTRE tenant obtient « not_found »)."""
        from jenny.api.auth.jwt_utils import create_access_token

        biz_a = uuid4()
        conv = str(uuid4())
        # Crée un état pour le business A (business_id dans le corps, sans auth).
        await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv,
                "business_id": str(biz_a),
                "message": "je veux une coupe femme mardi",
            },
        )
        # Token du PROPRIÉTAIRE (business A) → voit l'état.
        tok_a = create_access_token(uuid4(), "a@test.fr", [biz_a])
        r_owner = await client.get(
            f"/api/v1/conversation/status/{conv}",
            headers={"Authorization": f"Bearer {tok_a}"},
        )
        assert r_owner.json().get("status") != "not_found"
        # Token d'un AUTRE business → ne voit rien (IDOR fermé).
        tok_b = create_access_token(uuid4(), "b@test.fr", [uuid4()])
        r_other = await client.get(
            f"/api/v1/conversation/status/{conv}",
            headers={"Authorization": f"Bearer {tok_b}"},
        )
        assert r_other.json().get("status") == "not_found"

    @pytest.mark.asyncio
    async def test_multiturn_conversation(self, client: AsyncClient) -> None:
        """Conversation multi-tour — le contexte persiste."""
        conv_id = str(uuid4())
        business_id = str(uuid4())

        # Tour 1
        r1 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": business_id,
                "message": "Bonjour",
            },
        )
        assert r1.status_code == 200

        # Tour 2
        r2 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": business_id,
                "message": "Je cherche ma commande CMD-999",
            },
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["intent"] == "order_status"
