"""tests e2e de Jenny."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

# ajoute src au path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from jenny.api.main import create_app

# ═══════════════════════════════════════════════════════════
#  1. modèles ML
# ═══════════════════════════════════════════════════════════


class TestTrainedModels:
    """Modèles entraînés from scratch."""

    def test_intent_checkpoint_exists(self) -> None:
        """checkpoint intent présent."""
        assert Path("checkpoints/intent/best_model.pt").exists(), (
            "Le modèle Intent n'a pas été entraîné ! Lancez: python scripts/train_models.py"
        )

    def test_ner_checkpoint_exists(self) -> None:
        """checkpoint NER présent."""
        assert Path("checkpoints/ner/best_model.pt").exists(), (
            "Le modèle NER n'a pas été entraîné ! Lancez: python scripts/train_models.py"
        )

    def test_intent_predictions(self) -> None:
        """intent prédit bien."""
        from ml.models.intent.predict import IntentPredictor

        predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")

        # intent attendu détecté
        test_cases = [
            ("Où en est ma commande CMD-123 ?", ["order_status", "complaint"]),
            ("Je veux parler à un humain", ["escalation"]),
            ("Je voudrais prendre rendez-vous", ["appointment"]),
        ]

        for message, expected_intents in test_cases:
            result = predictor.predict_multi(message)
            detected = [d["intent"] for d in result["intents"]]
            assert any(ei in detected for ei in expected_intents), (
                f"Message: '{message}' → attendu l'un de {expected_intents}, obtenu {detected}"
            )

        # structure multi-label
        result = predictor.predict_multi("Je voudrais prendre rdv et avoir un devis")
        assert result["is_multi_intent"] is True or len(result["intents"]) >= 1
        assert result["primary_intent"] is not None
        assert result["primary_confidence"] > 0

    def test_ner_model_loads(self) -> None:
        """NER se charge."""
        from ml.models.ner.predict import NERPredictor

        predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")
        entities = predictor.predict("Ma commande CMD-12345 est en retard")
        # retourne quelque chose
        assert isinstance(entities, dict)

    def test_ner_tags(self) -> None:
        """NER sort des tags BIO."""
        from ml.models.ner.predict import NERPredictor

        predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")
        tags = predictor.predict_with_tags("Je suis Marie Dupont")
        assert len(tags) == 4  # 4 tokens
        assert all(isinstance(t, tuple) and len(t) == 2 for t in tags)


# ═══════════════════════════════════════════════════════════
#  2. agents métier
# ═══════════════════════════════════════════════════════════


class TestBusinessAgents:
    """agents métier."""

    @pytest.mark.asyncio
    async def test_payment_agent(self) -> None:
        """agent paiement répond."""
        from jenny.agents.payment_agent import PaymentAgent
        from jenny.engine.state_manager import ConversationState

        agent = PaymentAgent()
        state = ConversationState()
        state.set_intent("payment", 0.9)
        state.add_user_message("Comment payer ?")

        result = await agent.handle(state)
        assert "response" in result
        assert "Carte bancaire" in result["response"] or "paiement" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_quote_agent(self) -> None:
        """agent devis demande les infos."""
        from jenny.agents.quote_agent import QuoteAgent
        from jenny.engine.state_manager import ConversationState

        agent = QuoteAgent()
        state = ConversationState()
        state.set_intent("quote", 0.9)
        state.add_user_message("Je voudrais un devis")

        result = await agent.handle(state)
        assert "response" in result
        assert "devis" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_planning_agent(self) -> None:
        """agent planning: dispos."""
        from jenny.agents.planning_agent import PlanningAgent
        from jenny.engine.state_manager import ConversationState

        agent = PlanningAgent()
        state = ConversationState()
        state.set_intent("planning", 0.9)
        state.add_user_message("Quelles sont vos disponibilités ?")

        result = await agent.handle(state)
        assert "response" in result
        assert "action_result" in result
        assert result["action_result"]["type"] == "planning_info"
        assert (
            "available_slots_count" in result["action_result"]
            or "available_slots" in result["action_result"]
        )

    @pytest.mark.asyncio
    async def test_action_agent_with_registry(self) -> None:
        """action passe par le registre."""
        from jenny.actions.handlers.book_appointment import BookAppointmentAction
        from jenny.actions.handlers.check_planning import CheckPlanningAction
        from jenny.actions.handlers.create_ticket import CreateTicketAction
        from jenny.actions.handlers.generate_quote import GenerateQuoteAction
        from jenny.actions.handlers.order_check import CheckOrderAction
        from jenny.actions.handlers.process_payment import ProcessPaymentAction
        from jenny.actions.registry import ActionRegistry

        registry = ActionRegistry()
        registry.register(CheckOrderAction(), intents=["order_status"])
        registry.register(ProcessPaymentAction(), intents=["payment"])
        registry.register(GenerateQuoteAction(), intents=["quote"])
        registry.register(CheckPlanningAction(), intents=["planning"])
        registry.register(CreateTicketAction(), intents=["complaint"])
        registry.register(BookAppointmentAction(), intents=["appointment"])

        # toutes enregistrées
        actions = registry.list_actions()
        assert len(actions) == 6

        # résolution par intention
        assert registry.get_action("order_status") is not None
        assert registry.get_action("payment") is not None
        assert registry.get_action("quote") is not None
        assert registry.get_action("planning") is not None
        assert registry.get_action("complaint") is not None
        assert registry.get_action("appointment") is not None

    @pytest.mark.asyncio
    async def test_all_action_handlers_execute(self) -> None:
        """chaque handler tourne."""
        from jenny.actions.handlers.book_appointment import BookAppointmentAction
        from jenny.actions.handlers.check_planning import CheckPlanningAction
        from jenny.actions.handlers.create_ticket import CreateTicketAction
        from jenny.actions.handlers.generate_quote import GenerateQuoteAction
        from jenny.actions.handlers.order_check import CheckOrderAction
        from jenny.actions.handlers.process_payment import ProcessPaymentAction
        from jenny.db.repositories.order_repo import OrderRepository
        from jenny.db.repositories.support_ticket_repo import SupportTicketRepository

        bid = str(uuid4())
        # handlers autonomes: succès attendu
        self_contained = [
            (CheckOrderAction(), {"order_number": "CMD-123", "business_id": bid}),
            (ProcessPaymentAction(), {"order_number": "CMD-456", "amount": "99.99", "business_id": bid}),
            (CreateTicketAction(), {"email": "client@mail.com", "business_id": bid}),
            (BookAppointmentAction(), {"date": "20/03/2026"}),
        ]
        # sans contexte: déclinent proprement
        context_dependent = [
            (GenerateQuoteAction(), {"product": "iPhone 15", "email": "test@mail.com"}),
            (CheckPlanningAction(), {"date": "15/03/2026"}),
        ]

        fake_ticket = MagicMock()
        fake_ticket.id = uuid4()
        fake_ticket.reference = "TKT-e2e"
        fake_ticket.status = "open"

        with (
            patch.object(
                OrderRepository,
                "get_by_reference",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                SupportTicketRepository,
                "create_ticket",
                new_callable=AsyncMock,
                return_value=fake_ticket,
            ),
        ):
            for handler, params in self_contained:
                result = await handler.execute(params)
                assert result["success"] is True, f"{handler.name} a échoué: {result}"
                assert "message" in result, f"{handler.name} n'a pas de message"

            # enveloppe ok, pas de crash
            for handler, params in context_dependent:
                result = await handler.execute(params)
                assert isinstance(result, dict), f"{handler.name} n'a pas renvoyé un dict"
                assert isinstance(result.get("success"), bool), f"{handler.name}: 'success' manquant"
                assert result.get("message"), f"{handler.name} n'a pas de message"


# ═══════════════════════════════════════════════════════════
#  3. le RAG
# ═══════════════════════════════════════════════════════════


class TestRAG:
    """pipeline RAG complet."""

    @pytest.mark.asyncio
    async def test_chunking(self) -> None:
        """découpe en chunks."""
        from jenny.rag.ingestion import DocumentIngester

        ingester = DocumentIngester(chunk_size=100, chunk_overlap=20)
        text = (
            "Jenny est une plateforme IA pour les freelances. "
            "Elle gère les messages clients automatiquement. "
            "Jenny supporte Instagram, WhatsApp, email et formulaires. "
            "L'IA détecte les intentions et extrait les entités. "
            "Les agents spécialisés traitent chaque demande."
        )

        chunks = ingester.chunk_text(text, metadata={"source": "test"})
        assert len(chunks) >= 2
        assert all(len(c.content) > 0 for c in chunks)
        assert chunks[0].metadata["source"] == "test"

    @pytest.mark.asyncio
    async def test_memory_vector_store(self) -> None:
        """store mémoire: add + search."""
        from jenny.rag.memory_store import InMemoryVectorStore

        store = InMemoryVectorStore(collection="test")

        # ajoute des docs
        await store.add_document(
            content="Comment retourner un article ?",
            embedding=[1.0, 0.0, 0.0],
            metadata={"topic": "retour"},
        )
        await store.add_document(
            content="Nos tarifs sont compétitifs",
            embedding=[0.0, 1.0, 0.0],
            metadata={"topic": "pricing"},
        )
        await store.add_document(
            content="Politique de remboursement",
            embedding=[0.9, 0.1, 0.0],
            metadata={"topic": "retour"},
        )

        assert store.count == 3

        # recherche: doit trouver "retour"
        results = await store.search(
            query_embedding=[1.0, 0.0, 0.0],
            top_k=2,
        )
        assert len(results) == 2
        assert results[0].content == "Comment retourner un article ?"
        assert results[0].score > 0.9

    @pytest.mark.asyncio
    async def test_rag_pipeline_end_to_end(self) -> None:
        """RAG: ingestion puis recherche."""
        from jenny.rag.ingestion import DocumentIngester
        from jenny.rag.memory_store import InMemoryVectorStore

        store = InMemoryVectorStore(collection="faq")

        # embeddings bidons
        class SimpleEmbedder:
            """embedder bidon."""

            @property
            def dimension(self) -> int:
                return 8

            async def embed_text(self, text: str) -> list[float]:
                # hash en vecteur
                h = hash(text)
                return [(h >> i & 0xFF) / 255.0 for i in range(8)]

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed_text(t) for t in texts]

        embedder = SimpleEmbedder()
        ingester = DocumentIngester(
            embedder=embedder,
            vector_store=store,
            chunk_size=200,
        )

        # ingère une FAQ
        faq_text = (
            "Comment retourner un article ? "
            "Vous disposez de 30 jours pour retourner un article. "
            "Rendez-vous dans votre espace client, section 'Mes commandes'. "
            "Cliquez sur 'Retourner' et suivez les instructions."
        )

        num_chunks = await ingester.ingest_text(
            faq_text,
            metadata={"source": "faq", "topic": "retours"},
        )
        assert num_chunks >= 1
        assert store.count >= 1

        # recherche
        query_embedding = await embedder.embed_text("retourner un produit")
        results = await store.search(query_embedding=query_embedding, top_k=3)
        assert len(results) >= 1


# ═══════════════════════════════════════════════════════════
#  4. moteur conversationnel
# ═══════════════════════════════════════════════════════════


class TestConversationEngine:
    """moteur avec vrais modèles."""

    def _create_full_engine(self):
        """engine complet."""
        from jenny.actions.handlers.book_appointment import BookAppointmentAction
        from jenny.actions.handlers.check_planning import CheckPlanningAction
        from jenny.actions.handlers.create_ticket import CreateTicketAction
        from jenny.actions.handlers.generate_quote import GenerateQuoteAction
        from jenny.actions.handlers.order_check import CheckOrderAction
        from jenny.actions.handlers.process_payment import ProcessPaymentAction
        from jenny.actions.registry import ActionRegistry
        from jenny.agents.action_agent import ActionAgent
        from jenny.agents.fallback_agent import FallbackAgent
        from jenny.agents.faq_agent import FAQAgent
        from jenny.agents.payment_agent import PaymentAgent
        from jenny.agents.planning_agent import PlanningAgent
        from jenny.agents.quote_agent import QuoteAgent
        from jenny.agents.router import AgentRouter
        from jenny.engine.conversation_engine import ConversationEngine
        from jenny.engine.state_manager import StateManager

        # le registre
        registry = ActionRegistry()
        registry.register(CheckOrderAction(), intents=["order_status"])
        registry.register(ProcessPaymentAction(), intents=["payment"])
        registry.register(GenerateQuoteAction(), intents=["quote"])
        registry.register(CheckPlanningAction(), intents=["planning"])
        registry.register(CreateTicketAction(), intents=["complaint"])
        registry.register(BookAppointmentAction(), intents=["appointment"])

        # router + agents
        router = AgentRouter()
        router.register("faq", FAQAgent())
        router.register("action", ActionAgent(action_registry=registry))
        router.register("fallback", FallbackAgent())
        router.register("payment", PaymentAgent(action_registry=registry))
        router.register("quote", QuoteAgent(action_registry=registry))
        router.register("planning", PlanningAgent(action_registry=registry))

        # intent predictor
        intent_predictor = None
        if Path("checkpoints/intent/best_model.pt").exists():
            from ml.models.intent.predict import IntentPredictor

            intent_predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")

        # ner predictor
        ner_predictor = None
        if Path("checkpoints/ner/best_model.pt").exists():
            from ml.models.ner.predict import NERPredictor

            ner_predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")

        return ConversationEngine(
            state_manager=StateManager(),
            intent_predictor=intent_predictor,
            ner_predictor=ner_predictor,
            agent_router=router,
        )

    @pytest.mark.asyncio
    async def test_full_greeting_flow(self) -> None:
        """flow salutation."""
        from jenny.engine.conversation_engine import EngineRequest

        engine = self._create_full_engine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Bonjour !",
        )

        response = await engine.process(request)
        assert response.intent == "greeting"
        assert response.intent_confidence > 0.5
        assert response.response_text is not None
        assert len(response.response_text) > 0
        assert response.requires_human is False

    @pytest.mark.asyncio
    async def test_full_order_flow(self) -> None:
        """flow suivi commande."""
        from jenny.engine.conversation_engine import EngineRequest

        engine = self._create_full_engine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Où en est ma commande CMD-12345 ?",
        )

        response = await engine.process(request)
        assert response.intent == "order_status"
        assert response.response_text is not None
        assert response.agent_used == "action"

    @pytest.mark.asyncio
    async def test_full_escalation_flow(self) -> None:
        """flow escalation."""
        from jenny.engine.conversation_engine import EngineRequest

        engine = self._create_full_engine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Je veux parler à un humain",
        )

        response = await engine.process(request)
        assert response.intent == "escalation"
        assert response.requires_human is True

    @pytest.mark.asyncio
    async def test_full_payment_flow(self) -> None:
        """flow paiement."""
        from jenny.engine.conversation_engine import EngineRequest

        engine = self._create_full_engine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Comment payer ma facture ?",
        )

        response = await engine.process(request)
        # intent payment ou pricing
        assert response.intent in ("payment", "pricing", "faq")
        assert response.response_text is not None

    @pytest.mark.asyncio
    async def test_full_multiturn(self) -> None:
        """le contexte persiste."""
        from jenny.engine.conversation_engine import EngineRequest

        engine = self._create_full_engine()
        conv_id = uuid4()
        biz_id = uuid4()

        # tour 1: salutation
        r1 = await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=biz_id,
                message_text="Bonjour !",
            )
        )
        assert r1.intent == "greeting"

        # tour 2: commande
        r2 = await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=biz_id,
                message_text="Où en est ma commande CMD-999 ?",
            )
        )
        assert r2.intent == "order_status"

        # contexte maintenu
        state = engine.state_manager.get_or_create(conv_id, biz_id)
        assert state.turn_count >= 2


# ═══════════════════════════════════════════════════════════
#  5. langgraph
# ═══════════════════════════════════════════════════════════


class TestLangGraphIntegration:
    """teste le graphe LangGraph."""

    @pytest.mark.asyncio
    async def test_graph_greeting(self) -> None:
        """salutation sans escalade."""
        from jenny.agents.graph import process_message_with_graph

        result = await process_message_with_graph(
            message="Bonjour !",
            channel="form",
            sender="test_user",
        )
        assert result["intent"] is not None
        assert result["response"] is not None
        assert result["requires_human"] is False

    @pytest.mark.asyncio
    async def test_graph_escalation(self) -> None:
        """le graphe escalade."""
        from jenny.agents.graph import process_message_with_graph

        result = await process_message_with_graph(
            message="Je veux parler à un humain",
            channel="instagram",
        )
        assert result["requires_human"] is True

    @pytest.mark.asyncio
    async def test_graph_order_status(self) -> None:
        """route vers l'agent action."""
        from jenny.agents.graph import process_message_with_graph

        result = await process_message_with_graph(
            message="Où en est ma commande CMD-12345 ?",
            channel="whatsapp",
        )
        assert result["intent"] == "order_status"
        assert result["agent"] == "action"


# ═══════════════════════════════════════════════════════════
#  6. api endpoint
# ═══════════════════════════════════════════════════════════


class TestConversationAPI:
    """teste l'API chat."""

    @pytest.fixture
    async def client(self):
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c

    @pytest.mark.asyncio
    async def test_api_chat_full_flow(self, client: AsyncClient) -> None:
        """réponse structurée."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": str(uuid4()),
                "message": "Bonjour, je voudrais un devis pour une prestation photo",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "intent" in data
        assert "entities" in data

    @pytest.mark.asyncio
    async def test_api_health(self, client: AsyncClient) -> None:
        """healthcheck ok."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_api_multiturn(self, client: AsyncClient) -> None:
        """conversations multi-tours."""
        conv_id = str(uuid4())
        biz_id = str(uuid4())

        # Tour 1
        r1 = await client.post(
            "/api/v1/conversation/chat",
            json={"conversation_id": conv_id, "business_id": biz_id, "message": "Bonjour !"},
        )
        assert r1.status_code == 200

        # Tour 2
        r2 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Où en est ma commande ?",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["intent"] == "order_status"
