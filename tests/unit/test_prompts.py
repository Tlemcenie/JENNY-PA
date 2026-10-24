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

    def test_persona_sliders_sector_description_active(self) -> None:
        # Curseurs (positions franches), secteur et description doivent influencer
        # le prompt — ils étaient sauvegardés mais ignorés auparavant.
        out = build_persona_instructions(
            {
                "sliders": {"formel": 20, "concision": 15, "vente": 85},
                "sector": "Maroquinerie artisanale",
                "description": "Atelier de sacs en cuir cousus main.",
            }
        )
        assert "soutenu" in out  # formel ≤ 35
        assert "courtes" in out  # concision ≤ 35
        assert "réservation" in out.lower()  # vente ≥ 65
        assert "Maroquinerie artisanale" in out
        assert "cousus main" in out

    def test_persona_sliders_neutral_emit_nothing(self) -> None:
        # Autour du neutre (~50), aucun curseur ne doit brider le ton.
        out = build_persona_instructions(
            {"sliders": {"formel": 50, "concision": 50, "vente": 50}}
        )
        assert out == ""

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
        # les docs passent par le prompt SYSTÈME (comme le chemin normal),
        # le prompt utilisateur garde la question + l'historique
        builder = PromptBuilder()
        state = ConversationState()
        state.add_user_message("Quels sont vos horaires ?")

        documents = [
            {"content": "Ouvert du lundi au vendredi, 9h-18h", "score": 0.95},
        ]
        state.retrieved_documents = documents
        system = builder.build_rag_system_prompt(state)
        user = builder.build_rag_user_prompt(state, documents)
        assert "9h-18h" in system
        assert "horaires" in user

    def test_rag_prompt_garde_les_regles_de_base(self) -> None:
        # avant : le chemin RAG repartait de zéro et perdait le ton + les faits
        builder = PromptBuilder()
        state = ConversationState()
        state.add_user_message("vous avez de la place jeudi ?")
        state.retrieved_documents = [{"content": "Infos salon", "score": 0.4}]
        state.action_result = {"success": True, "day": "jeudi 24/07", "time": "14h00"}

        system = builder.build_rag_system_prompt(state)
        assert "À DIRE AU CLIENT" in system  # les faits d'action survivent
        assert "jeudi 24/07" in system  # le créneau réel est verrouillé

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
