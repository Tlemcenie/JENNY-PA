"""scénarios coiffeur, sans ner, head ou lstm.

Rejoue tests/e2e/test_user_coiffeur.py avec les réglages de service :
intent_model_kind = head | lstm et enable_ner_model = False (regex du
moteur). Le moteur direct ET la fabrique (graphe, API) sont couverts.
"""

from pathlib import Path
from uuid import uuid4

import pytest

import tests.e2e.test_user_coiffeur as base
from jenny.core.config import get_settings
from jenny.engine import factory
from tests.e2e.test_user_coiffeur import (
    TestClarification,
    TestMultiLabelIntents,
    TestRDVUrgentAvecDevis,
    TestScenarioAPICoiffeur,
    TestScenarioDevisMariage,
    TestScenarioFAQ,
    TestScenarioLangGraphCoiffeur,
    TestScenarioMessagesRealistesSalon,
    TestScenarioModificationRDV,
    TestScenarioMultiCanal,
    TestScenarioPaiement,
    TestScenarioPriseDeRDV,
    TestScenarioReclamation,
    TestScenarioRobustesse,
    TestScenarioSalutations,
    TestScenarioSuiviCommande,
    TestScenarioTarifs,
)

__all__ = [
    "TestClarification",
    "TestMultiLabelIntents",
    "TestRDVUrgentAvecDevis",
    "TestScenarioAPICoiffeur",
    "TestScenarioConversationComplete",
    "TestScenarioDevisMariage",
    "TestScenarioFAQ",
    "TestScenarioLangGraphCoiffeur",
    "TestScenarioMessagesRealistesSalon",
    "TestScenarioModificationRDV",
    "TestScenarioMultiCanal",
    "TestScenarioPaiement",
    "TestScenarioPriseDeRDV",
    "TestScenarioReclamation",
    "TestScenarioRobustesse",
    "TestScenarioSalutations",
    "TestScenarioSuiviCommande",
    "TestScenarioTarifs",
]

_ORIG_BUILD = base._build_engine
_PREDICTORS: dict[str, object] = {}

# écarts connus, vérifiés (strict)
KNOWN_FAILS = {
    ("lstm", "test_api_tarifs"): "lstm : tarifs des coupes -> faq à 0,99 (erreur préexistante)",
}


def _predictor(kind: str) -> object:
    """un prédicteur par type."""
    if kind not in _PREDICTORS:
        pred = factory.load_intent_predictor(kind, fallback=False)
        if pred is None:
            pytest.skip(f"prédicteur {kind} indisponible")
        _PREDICTORS[kind] = pred
    return _PREDICTORS[kind]


@pytest.fixture(autouse=True, params=["head", "lstm"])
def intent_kind(request, monkeypatch):
    """réglages de service, sans ner."""
    kind = request.param
    reason = KNOWN_FAILS.get((kind, request.node.originalname))
    if reason:
        request.applymarker(pytest.mark.xfail(reason=reason, strict=True))
    if kind == "head" and not Path("checkpoints/intent_head/head.npz").exists():
        pytest.skip("checkpoint tête absent")
    monkeypatch.setenv("JENNY_ENABLE_ML_MODELS", "true")
    monkeypatch.setenv("JENNY_INTENT_MODEL_KIND", kind)
    monkeypatch.setenv("JENNY_ENABLE_NER_MODEL", "false")
    get_settings.cache_clear()
    factory.reset_engine()
    pred = _predictor(kind)

    def build():
        engine = _ORIG_BUILD()
        engine.intent_predictor = pred
        engine.ner_predictor = None
        return engine

    monkeypatch.setattr(base, "_build_engine", build)
    yield kind
    get_settings.cache_clear()
    factory.reset_engine()


class TestScenarioConversationComplete:
    """Emma, parcours complet."""

    @pytest.mark.asyncio
    async def test_emma_parcours_complet(self) -> None:
        """Même parcours que la base."""
        engine = base._build_engine()
        conv_id = uuid4()

        r1 = await base._send(engine, conv_id, "Hello !")
        assert r1.intent == "greeting"

        r2 = await base._send(engine, conv_id, "Je voudrais prendre rdv pour une coloration")
        assert r2.intent in ("appointment", "planning")

        r3 = await base._send(engine, conv_id, "C'est combien pour une colo + mèches ?")
        assert r3.intent in ("pricing", "faq", "planning")

        # étalement : payment_question à 34/17
        r4 = await base._send(engine, conv_id, "Ok, je peux payer en plusieurs fois ?")
        assert r4.intent in ("payment", "payment_question")
        assert r4.agent_used == "payment"
        assert "paiement" in r4.response_text.lower() or len(r4.response_text) > 10

        r5 = await base._send(engine, conv_id, "Parfait merci ! À bientôt")
        assert r5.intent == "closing"

        state = engine.state_manager.get_or_create(conv_id, uuid4())
        assert state.turn_count == 5
        assert len(state.message_history) == 10
