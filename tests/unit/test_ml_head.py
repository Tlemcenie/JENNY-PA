"""non-régression de la tête mpnet."""

import hashlib
from pathlib import Path

import pytest

from ml.models.intent.config import INTENT_LABELS
from ml.models.intent.predict import IntentPredictor
from ml.models.intent_head.data import DATA_PATH, frozen_split, labels_of, load_rows
from ml.models.intent_head.predict import DEFAULT_PATH, EmbeddingIntentPredictor

LSTM_PATH = Path("checkpoints/intent/best_model.pt")
KEYS = {
    "intents",
    "primary_intent",
    "primary_confidence",
    "is_multi_intent",
    "all_scores",
    "needs_clarification",
}
# échantillon figé, niveau du lstm
N_SAMPLE = 200
FLOOR_SAMPLE = 87.0


@pytest.fixture(scope="module")
def head() -> EmbeddingIntentPredictor:
    if not DEFAULT_PATH.exists():
        pytest.skip("checkpoint tête absent")
    try:
        return EmbeddingIntentPredictor.from_checkpoint(DEFAULT_PATH)
    except OSError as e:
        pytest.skip(f"encodeur indisponible : {e}")


class TestForme:
    """même contrat que le lstm."""

    def test_vu_comme_intent_predictor(self, head) -> None:
        # le moteur teste isinstance
        assert isinstance(head, IntentPredictor)
        assert head.labels == INTENT_LABELS

    def test_dict_predict_multi(self, head) -> None:
        res = head.predict_multi("Bonjour, je voudrais un rendez-vous samedi")
        assert set(res) == KEYS
        assert set(res["all_scores"]) == set(INTENT_LABELS)
        assert abs(sum(res["all_scores"].values()) - 1.0) < 1e-2
        assert res["primary_intent"] == res["intents"][0]["intent"]
        assert res["primary_confidence"] == res["intents"][0]["confidence"]
        assert res["is_multi_intent"] == (len(res["intents"]) > 1)
        assert 1 <= len(res["intents"]) <= 3
        confs = [d["confidence"] for d in res["intents"]]
        assert confs == sorted(confs, reverse=True)
        assert isinstance(res["needs_clarification"], bool)

    def test_memes_cles_que_lstm(self, head) -> None:
        if not LSTM_PATH.exists():
            pytest.skip("checkpoint lstm absent")
        lstm = IntentPredictor.from_checkpoint(LSTM_PATH)
        texte = "combien pour une coupe"
        assert set(lstm.predict_multi(texte)) == set(head.predict_multi(texte))
        assert set(lstm.predict(texte)) == set(head.predict(texte))

    def test_texte_vide(self, head) -> None:
        res = head.predict_multi("")
        assert set(res) == KEYS
        assert res["primary_intent"] in INTENT_LABELS

    def test_batch_egal_unitaire(self, head) -> None:
        textes = ["bjr", "mon colis n'est pas arrivé", "je veux parler à un conseiller"]
        batch = head.predict_batch_multi(textes)
        for t, b in zip(textes, batch, strict=True):
            assert b["primary_intent"] == head.predict_multi(t)["primary_intent"]


class TestPrecision:
    """plancher sur le test figé."""

    def test_checkpoint_du_bon_jeu(self, head) -> None:
        meta = head.meta
        assert meta["data_sha256"] == hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
        # train seul
        assert meta["train_lignes"] == meta["split"]["train"] == 3542

    def test_plancher_test(self, head) -> None:
        rows = load_rows()
        idx = frozen_split(len(rows))["test"][:N_SAMPLE]
        preds = head.predict_batch_multi([rows[i]["text"] for i in idx])
        ok = sum(
            p["primary_intent"] == labels_of(rows[i])[0] for p, i in zip(preds, idx, strict=True)
        )
        assert 100 * ok / len(idx) >= FLOOR_SAMPLE


class TestSMS:
    """messages écrits comme un client."""

    @pytest.mark.parametrize(
        ("texte", "attendus"),
        [
            ("jvoudrais un rdv demain", {"appointment", "planning"}),
            ("cbien la coupe", {"pricing", "quote"}),
            ("vs etes ouvert dimanche", {"planning", "faq"}),
            ("bjr", {"greeting"}),
            ("je veux parler a un humain", {"escalation"}),
            ("mon colis est tjrs pas arrive", {"order_status", "complaint"}),
            ("vs prenez la cb", {"payment_question", "payment"}),
            ("mrc bcp bonne journee", {"closing"}),
        ],
    )
    def test_sms(self, head, texte, attendus) -> None:
        res = head.predict_multi(texte)
        assert res["primary_intent"] in attendus, res["all_scores"]
