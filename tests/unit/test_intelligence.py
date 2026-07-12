"""Tests unitaires de la couche d'intelligence du moteur (fonctions pures)."""

from __future__ import annotations

from jenny.engine.intelligence import (
    ClarificationDecision,
    decide_clarification,
    detect_language,
    extract_customer_facts,
    is_knowledge_gap,
    looks_like_deflection,
    normalize_question,
    refine_knowledge_gap,
)


class TestLanguage:
    def test_detects_english(self) -> None:
        assert detect_language("Hello, are you open on Sunday afternoon?") == "en"

    def test_detects_spanish(self) -> None:
        assert detect_language("Hola, quiero reservar una cita para mañana") == "es"

    def test_short_message_defaults_to_french(self) -> None:
        # Trop court pour une détection fiable → défaut.
        assert detect_language("Bonjour") == "fr"
        assert detect_language("ok") == "fr"


class TestClarification:
    def test_vague_message_triggers(self) -> None:
        d = decide_clarification(
            message_text="info", intent="general", confidence=0.3, entities={}
        )
        assert d.needs_clarification and d.reason == "too_vague"

    def test_missing_order_number_triggers(self) -> None:
        d = decide_clarification(
            message_text="où est ma commande ?",
            intent="order_status",
            confidence=0.8,
            entities={},
        )
        assert d.needs_clarification and d.reason == "missing_entity"

    def test_order_with_number_does_not_trigger(self) -> None:
        d = decide_clarification(
            message_text="où est ma commande CMD-12345 ?",
            intent="order_status",
            confidence=0.8,
            entities={"order_number": "CMD-12345"},
        )
        assert not d.needs_clarification

    def test_greeting_never_clarifies(self) -> None:
        d = decide_clarification(
            message_text="bonjour", intent="greeting", confidence=0.2, entities={}
        )
        assert d == ClarificationDecision.none()

    def test_multi_intent_triggers(self) -> None:
        d = decide_clarification(
            message_text="je veux un devis et payer ma facture",
            intent="quote",
            confidence=0.6,
            entities={},
            detected_intents=[
                {"intent": "quote", "confidence": 0.6},
                {"intent": "payment", "confidence": 0.55},
            ],
            is_multi_intent=True,
        )
        assert d.needs_clarification and d.reason == "multi_intent"


class TestKnowledgeGap:
    def test_no_docs_is_gap(self) -> None:
        assert is_knowledge_gap(intent="faq", documents=[], action_result=None) is True

    def test_relevant_doc_not_gap(self) -> None:
        assert (
            is_knowledge_gap(
                intent="faq", documents=[{"score": 0.7}], action_result=None
            )
            is False
        )

    def test_low_score_is_gap(self) -> None:
        assert (
            is_knowledge_gap(
                intent="pricing", documents=[{"score": 0.1}], action_result=None
            )
            is True
        )

    def test_action_result_not_gap(self) -> None:
        assert (
            is_knowledge_gap(
                intent="order_status",
                documents=[],
                action_result={"success": True, "status": "expédiée"},
            )
            is False
        )

    def test_non_knowledge_intent_not_gap(self) -> None:
        assert is_knowledge_gap(intent="greeting", documents=[], action_result=None) is False


class TestFacts:
    def test_extracts_allergy_and_preference(self) -> None:
        facts = extract_customer_facts(
            "Bonjour, je suis allergique au gluten et je préfère les rendez-vous le matin."
        )
        kinds = {f["kind"] for f in facts}
        assert "constraint" in kinds and "preference" in kinds
        # Le fait d'allergie ne doit pas avoir avalé la suite (coupé à « et »).
        allergy = next(f for f in facts if f["kind"] == "constraint")
        assert "gluten" in allergy["fact"].lower()
        assert "préfère" not in allergy["fact"].lower()

    def test_no_facts_in_plain_message(self) -> None:
        assert extract_customer_facts("Quels sont vos horaires ?") == []


class TestNormalize:
    def test_dedup_key_ignores_accents_punct_case(self) -> None:
        a = normalize_question("Vous êtes ouverts le Dimanche ?")
        b = normalize_question("vous etes ouverts le dimanche")
        assert a == b


class TestDeflectionRefine:
    def test_detects_deflection(self) -> None:
        assert looks_like_deflection("Je vérifie ça auprès de l'équipe et je reviens vers vous !")
        assert looks_like_deflection("Je me renseigne et je vous recontacte.")

    def test_direct_answer_not_deflection(self) -> None:
        assert not looks_like_deflection("Une coupe homme coûte 25 euros.")

    def test_refine_catches_deflection_despite_doc(self) -> None:
        # Un document proche existait (pre_gap=False) mais Jenny a esquivé → lacune.
        assert refine_knowledge_gap(
            intent="general",
            response_text="Je vérifie auprès de l'équipe et je reviens vers vous.",
            action_result=None,
            pre_gap=False,
            needs_clarification=False,
        )

    def test_refine_not_gap_when_answered(self) -> None:
        assert not refine_knowledge_gap(
            intent="pricing",
            response_text="Le balayage est à 80€.",
            action_result=None,
            pre_gap=False,
            needs_clarification=False,
        )

    def test_refine_not_gap_when_genuinely_clarifying(self) -> None:
        # Vraie clarification (une QUESTION, sans formule de déflexion) : ce n'est
        # pas « je ne sais pas » mais « je n'ai pas compris » → pas une lacune.
        assert not refine_knowledge_gap(
            intent="general",
            response_text="Bien sûr ! Vous parlez d'une coupe ou d'une coloration ?",
            action_result=None,
            pre_gap=True,
            needs_clarification=True,
        )

    def test_refine_gap_when_deflecting_even_if_clarifying(self) -> None:
        # Une DÉFLEXION reste une lacune même si le classifieur a signalé une
        # clarification (souvent une simple hésitation) : Jenny a esquivé.
        assert refine_knowledge_gap(
            intent="general",
            response_text="Je vérifie et je reviens vers vous.",
            action_result=None,
            pre_gap=False,
            needs_clarification=True,
        )

    def test_refine_not_gap_when_deflecting_on_grounded_content(self) -> None:
        # Le contenu EST en base (retrieval_grounded) mais le petit modèle esquive
        # par paresse (« je vérifie ») → PAS une lacune (on ne loggue pas une
        # fausse « question sans réponse » au gérant). Cas « comment annuler ? »
        # alors que la KB dit « appelez le salon / SMS ».
        assert not refine_knowledge_gap(
            intent="faq",
            response_text="Je vérifie ça tout de suite et je reviens vers vous !",
            action_result=None,
            pre_gap=False,
            needs_clarification=False,
            retrieval_grounded=True,
        )
