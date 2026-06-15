"""Tests unitaires pour le moteur conversationnel."""

from uuid import uuid4

import pytest

from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
from jenny.engine.state_manager import (
    ConversationPhase,
    ConversationState,
    ExtractedSlot,
    StateManager,
)

# ── StateManager ──


class TestStateManager:
    """Tests pour le gestionnaire d'état conversationnel."""

    def test_create_state(self) -> None:
        """Crée un nouvel état de conversation."""
        manager = StateManager()
        conv_id = uuid4()
        state = manager.get_or_create(conv_id)

        assert state.conversation_id == conv_id
        assert state.phase == ConversationPhase.GREETING
        assert state.turn_count == 0

    def test_get_existing_state(self) -> None:
        """Récupère un état existant sans le recréer."""
        manager = StateManager()
        conv_id = uuid4()
        state1 = manager.get_or_create(conv_id)
        state1.turn_count = 3
        manager.save(state1)

        state2 = manager.get_or_create(conv_id)
        assert state2.turn_count == 3

    def test_delete_state(self) -> None:
        """Supprime un état."""
        manager = StateManager()
        conv_id = uuid4()
        manager.get_or_create(conv_id)
        manager.delete(conv_id)
        assert manager.get(conv_id) is None


# ── ConversationState ──


class TestConversationState:
    """Tests pour l'état de conversation."""

    def test_add_user_message(self) -> None:
        state = ConversationState()
        state.add_user_message("Bonjour")
        assert len(state.message_history) == 1
        assert state.message_history[0]["role"] == "user"
        assert state.turn_count == 1

    def test_add_assistant_message(self) -> None:
        state = ConversationState()
        state.add_assistant_message("Comment puis-je vous aider ?")
        assert len(state.message_history) == 1
        assert state.message_history[0]["role"] == "assistant"

    def test_set_intent(self) -> None:
        state = ConversationState()
        state.set_intent("order_status", 0.95)
        assert state.current_intent == "order_status"
        assert state.intent_confidence == 0.95

    def test_intent_history(self) -> None:
        state = ConversationState()
        state.set_intent("greeting", 0.9)
        state.set_intent("order_status", 0.85)
        assert "greeting" in state.previous_intents
        assert state.current_intent == "order_status"

    def test_set_slot(self) -> None:
        state = ConversationState()
        state.set_slot("order_number", "CMD-123", entity_type="ORDER_NUMBER")
        assert state.slots["order_number"].value == "CMD-123"
        assert state.slots["order_number"].filled is True

    def test_missing_required_slots(self) -> None:
        state = ConversationState()
        state.slots["order_number"] = ExtractedSlot(
            name="order_number",
            required=True,
            filled=False,
        )
        assert state.has_missing_required_slots() is True
        assert len(state.get_missing_slots()) == 1

    def test_max_history_truncation(self) -> None:
        state = ConversationState(max_history=3)
        for i in range(5):
            state.add_user_message(f"message {i}")
        assert len(state.message_history) == 3

    def test_context_summary(self) -> None:
        state = ConversationState()
        state.set_intent("order_status", 0.9)
        state.set_slot("order_number", "CMD-123")
        summary = state.get_context_summary()
        assert "order_status" in summary
        assert "CMD-123" in summary


# ── ConversationEngine ──


class TestConversationEngine:
    """Tests pour le moteur conversationnel."""

    @pytest.mark.asyncio
    async def test_process_greeting(self) -> None:
        """Traite un message de salutation."""
        engine = ConversationEngine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Bonjour !",
        )
        response = await engine.process(request)
        assert response.response_text is not None
        assert response.intent == "greeting"

    @pytest.mark.asyncio
    async def test_process_order_status(self) -> None:
        """Traite une demande de suivi de commande."""
        engine = ConversationEngine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Où en est ma commande CMD-12345 ?",
        )
        response = await engine.process(request)
        assert response.intent == "order_status"
        # L'entité devrait être extraite par regex
        if response.entities:
            assert "order_number" in response.entities

    @pytest.mark.asyncio
    async def test_process_escalation(self) -> None:
        """Détecte une demande d'escalation."""
        engine = ConversationEngine()
        request = EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Je veux parler à un humain",
        )
        response = await engine.process(request)
        assert response.intent == "escalation"
        assert response.requires_human is True

    @pytest.mark.asyncio
    async def test_greeting_does_not_mask_request(self) -> None:
        """Une salutation en tête ne doit pas masquer la vraie demande."""
        engine = ConversationEngine()
        result = await engine._detect_intent("Bonjour, je voudrais un devis", None)
        assert result["intent"] == "quote"
        assert result.get("was_greeting") is True
        # La salutation reste tracée comme intention secondaire.
        assert any(d["intent"] == "greeting" for d in result["detected_intents"])

    @pytest.mark.asyncio
    async def test_greeting_with_appointment(self) -> None:
        """« Salut, je veux un rendez-vous » → appointment, pas greeting."""
        engine = ConversationEngine()
        result = await engine._detect_intent("Salut, je veux prendre rendez-vous", None)
        assert result["intent"] == "appointment"
        assert result.get("was_greeting") is True

    @pytest.mark.asyncio
    async def test_pure_greeting_stays_greeting(self) -> None:
        """Un message de pure politesse reste une salutation."""
        engine = ConversationEngine()
        result = await engine._detect_intent("Bonjour !", None)
        assert result["intent"] == "greeting"
        assert result.get("was_greeting") is None

    def test_strip_leading_greeting(self) -> None:
        """Le retrait de salutation isole le reste du message."""
        engine = ConversationEngine()
        assert engine._strip_leading_greeting("Bonjour, je veux un devis") == "je veux un devis"
        assert engine._strip_leading_greeting("Salut ! Ça va ?") == "Ça va ?"
        # Pure salutation → rien de substantiel à reclasser.
        assert engine._strip_leading_greeting("Bonjour !") == ""
        assert engine._strip_leading_greeting("Bonjour") == ""
        # Pas de salutation → pas de remainder.
        assert engine._strip_leading_greeting("Je veux un devis") == ""
        # Fragment trop court (un prénom) → pas une demande, on n'override pas.
        assert engine._strip_leading_greeting("Bonjour Jenny !") == ""
        # Pas de faux positif sur un mot qui commence comme une salutation.
        assert engine._strip_leading_greeting("Himalaya trek inoubliable") == ""

    @pytest.mark.asyncio
    async def test_multiturn_context(self) -> None:
        """Vérifie que le contexte persiste entre les tours."""
        engine = ConversationEngine()
        conv_id = uuid4()
        business_id = uuid4()

        # Tour 1
        await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=business_id,
                message_text="Bonjour",
            )
        )

        # Tour 2
        await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=business_id,
                message_text="Ma commande CMD-999",
            )
        )

        # Vérifier que le state a été mis à jour
        state = engine.state_manager.get(conv_id)
        assert state is not None
        assert state.turn_count == 2

    @pytest.mark.asyncio
    async def test_regex_entity_extraction(self) -> None:
        """Extraction d'entités par regex (fallback)."""
        engine = ConversationEngine()
        entities = engine._regex_entity_extraction(
            "Mon email est test@example.com et ma commande CMD-ABC123"
        )
        assert entities.get("email") == "test@example.com"
        assert "ABC123" in entities.get("order_number", "")

    @pytest.mark.asyncio
    async def test_regex_phone_extraction(self) -> None:
        """Extraction d'un numéro de téléphone."""
        engine = ConversationEngine()
        entities = engine._regex_entity_extraction("Appelez-moi au 06 12 34 56 78")
        assert "phone" in entities

    @pytest.mark.asyncio
    async def test_regex_amount_extraction(self) -> None:
        """Extraction d'un montant."""
        engine = ConversationEngine()
        entities = engine._regex_entity_extraction("Le montant est de 150,50 €")
        assert entities.get("amount") == "150,50"
