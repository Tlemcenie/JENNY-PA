"""Tests unitaires pour les agents et le routeur."""

import pytest

from jenny.agents.action_agent import ActionAgent
from jenny.agents.fallback_agent import FallbackAgent
from jenny.agents.faq_agent import FAQAgent
from jenny.agents.router import AgentRouter
from jenny.engine.state_manager import ConversationState


class TestAgentRouter:
    """Tests pour le répartiteur d'agents."""

    @pytest.mark.asyncio
    async def test_route_escalation(self) -> None:
        """L'escalation retourne requires_human=True."""
        router = AgentRouter()
        state = ConversationState()
        state.set_intent("escalation", 0.95)

        result = await router.route(state)
        assert result["agent"] == "escalation"
        assert result["requires_human"] is True

    @pytest.mark.asyncio
    async def test_route_low_confidence(self) -> None:
        """Confiance faible → fallback."""
        router = AgentRouter()
        fallback = FallbackAgent()
        router.register("fallback", fallback)

        state = ConversationState()
        state.set_intent("order_status", 0.2)  # Confiance trop basse

        result = await router.route(state)
        assert result["agent"] == "fallback"

    @pytest.mark.asyncio
    async def test_route_to_faq(self) -> None:
        """Intention FAQ → agent FAQ."""
        router = AgentRouter()
        faq = FAQAgent()
        router.register("faq", faq)

        state = ConversationState()
        state.set_intent("faq", 0.85)
        state.add_user_message("Comment ça marche ?")

        result = await router.route(state)
        assert result["agent"] == "faq"

    @pytest.mark.asyncio
    async def test_route_agent_not_found(self) -> None:
        """Agent non enregistré → fallback."""
        router = AgentRouter()
        state = ConversationState()
        state.set_intent("order_status", 0.9)

        result = await router.route(state)
        assert result["agent"] == "fallback"


class TestFallbackAgent:
    """Tests pour l'agent fallback."""

    @pytest.mark.asyncio
    async def test_greeting(self) -> None:
        agent = FallbackAgent()
        state = ConversationState()
        state.set_intent("greeting", 0.9)

        result = await agent.handle(state)
        assert "Bonjour" in result["response"]

    @pytest.mark.asyncio
    async def test_closing(self) -> None:
        agent = FallbackAgent()
        state = ConversationState()
        state.set_intent("closing", 0.9)

        result = await agent.handle(state)
        assert "Merci" in result["response"]

    @pytest.mark.asyncio
    async def test_low_confidence(self) -> None:
        agent = FallbackAgent()
        state = ConversationState()
        state.set_intent("unknown", 0.2)

        result = await agent.handle(state)
        assert "reformuler" in result["response"]


class TestFAQAgent:
    """Tests pour l'agent FAQ."""

    @pytest.mark.asyncio
    async def test_no_retriever(self) -> None:
        """Sans retriever, retourne un message par défaut."""
        agent = FAQAgent(retriever=None)
        state = ConversationState()
        state.add_user_message("Quels sont vos horaires ?")

        result = await agent.handle(state)
        assert "action_result" in result
        assert result["documents"] == []

    @pytest.mark.asyncio
    async def test_no_user_message(self) -> None:
        """Sans message utilisateur, retourne une question."""
        agent = FAQAgent()
        state = ConversationState()

        result = await agent.handle(state)
        assert "Comment puis-je vous aider" in result["response"]


class TestActionAgent:
    """Tests pour l'agent d'action."""

    @pytest.mark.asyncio
    async def test_missing_slots(self) -> None:
        """Slots manquants → demande d'info."""
        agent = ActionAgent()
        state = ConversationState()
        state.set_intent("order_status", 0.9)

        result = await agent.handle(state)
        assert result.get("needs_more_info") is True

    @pytest.mark.asyncio
    async def test_with_filled_slots(self) -> None:
        """Slots remplis → exécution simulée."""
        agent = ActionAgent()
        state = ConversationState()
        state.set_intent("order_status", 0.9)
        state.set_slot("order_number", "CMD-123")

        result = await agent.handle(state)
        assert result["action_result"] is not None
