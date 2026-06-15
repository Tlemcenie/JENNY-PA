"""Tests pour le système de prompts."""

from jenny.engine.state_manager import ConversationState, ExtractedSlot
from jenny.llm.prompts import PromptBuilder, build_persona_instructions


class TestPromptBuilder:
    """Tests pour la construction de prompts."""

    def test_system_prompt_base(self) -> None:
        builder = PromptBuilder(business_type="un salon de coiffure")
        state = ConversationState()
        prompt = builder.build_system_prompt(state)
        assert "Jenny" in prompt
        assert "salon de coiffure" in prompt

    def test_persona_none_leaves_prompt_unchanged(self) -> None:
        # Sans persona, le prompt système est inchangé (pas de régression).
        assert build_persona_instructions(None) == ""
        builder = PromptBuilder()
        assert "définis par l'équipe" not in builder.build_system_prompt(ConversationState())

    def test_persona_shapes_system_prompt(self) -> None:
        # Le « Cerveau de Jenny » (ton/tutoiement/vocabulaire/règles) est injecté.
        builder = PromptBuilder()
        state = ConversationState()
        state.business_persona = {
            "tone": "cool",
            "tutoiement": True,
            "vocab": ["l'atelier", "fait main"],
            "rules": [
                {"label": "Ne jamais promettre < 48h", "on": True},
                {"label": "Règle désactivée", "on": False},
            ],
        }
        state.business_name = "Maison Lila"
        prompt = builder.build_system_prompt(state)
        assert "décontracté" in prompt  # ton cool
        assert "Tutoie" in prompt
        assert "l'atelier" in prompt
        assert "Ne jamais promettre < 48h" in prompt
        assert "Règle désactivée" not in prompt  # règle off → exclue
        assert "Maison Lila" in prompt

    def test_persona_injected_in_rag_prompt(self) -> None:
        builder = PromptBuilder()
        state = ConversationState()
        state.business_persona = {"tone": "vendeur"}
        prompt = builder.build_rag_system_prompt(state)
        assert "persuasif" in prompt

    def test_system_prompt_with_intent(self) -> None:
        builder = PromptBuilder()
        state = ConversationState()
        state.set_intent("order_status", 0.9)
        prompt = builder.build_system_prompt(state)
        # Le prompt contient le contexte de l'intention (pas le label brut)
        assert "commande" in prompt.lower()

    def test_user_prompt_with_history(self) -> None:
        builder = PromptBuilder()
        state = ConversationState()
        state.add_user_message("Bonjour")
        state.add_assistant_message("Comment puis-je vous aider ?")
        state.add_user_message("Ma commande")

        prompt = builder.build_user_prompt(state)
        assert "Bonjour" in prompt
        assert "Ma commande" in prompt

    def test_rag_prompt_with_documents(self) -> None:
        builder = PromptBuilder()
        state = ConversationState()
        state.add_user_message("Quels sont vos horaires ?")

        documents = [
            {"content": "Ouvert du lundi au vendredi, 9h-18h", "score": 0.95},
        ]
        prompt = builder.build_rag_user_prompt(state, documents)
        assert "9h-18h" in prompt
        assert "horaires" in prompt

    def test_slot_filling_prompt(self) -> None:
        builder = PromptBuilder()
        state = ConversationState()
        state.slots["order_number"] = ExtractedSlot(
            name="order_number",
            required=True,
            filled=False,
        )
        prompt = builder.build_slot_filling_prompt(state)
        assert "order_number" in prompt
