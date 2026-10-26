"""réglages ml de la fabrique."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from jenny.core.config import Settings, get_settings
from jenny.engine import factory
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder
from jenny.rag.retriever import VectorRetriever
from ml.models.intent.predict import IntentPredictor
from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor
from ml.models.ner.predict import NERPredictor

HEAD_OK = Path("checkpoints/intent_head/head.joblib").exists()
LSTM_OK = Path("checkpoints/intent/best_model.pt").exists()
NER_OK = Path("checkpoints/ner/best_model.pt").exists()


@pytest.fixture
def env(monkeypatch):
    """pose des variables JENNY_*."""

    def _set(**values: object) -> None:
        for k, v in values.items():
            monkeypatch.setenv(f"JENNY_{k.upper()}", str(v))
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


class TestReglages:
    """valeurs et validation."""

    def test_defauts(self, monkeypatch) -> None:
        monkeypatch.delenv("JENNY_INTENT_MODEL_KIND", raising=False)
        monkeypatch.delenv("JENNY_ENABLE_NER_MODEL", raising=False)
        s = Settings(_env_file=None)
        assert s.intent_model_kind == "head"
        assert s.enable_ner_model is False
        assert s.intent_head_path == "checkpoints/intent_head/head.joblib"

    def test_type_inconnu_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, intent_model_kind="bert")


class TestChargement:
    """head, lstm, ner, repli."""

    def test_ml_coupe(self, env) -> None:
        env(enable_ml_models="false")
        assert factory.load_ml_predictors() == (None, None)

    @pytest.mark.skipif(not HEAD_OK, reason="checkpoint tête absent")
    def test_head_sans_ner(self, env) -> None:
        env(enable_ml_models="true", intent_model_kind="head")
        intent, ner = factory.load_ml_predictors()
        assert isinstance(intent, EmbeddingIntentPredictor)
        assert ner is None

    @pytest.mark.skipif(not LSTM_OK, reason="checkpoint lstm absent")
    def test_lstm_reste_chargeable(self, env) -> None:
        env(enable_ml_models="true", intent_model_kind="lstm")
        intent, ner = factory.load_ml_predictors()
        assert type(intent) is IntentPredictor
        assert ner is None

    @pytest.mark.skipif(not (LSTM_OK and NER_OK), reason="checkpoints absents")
    def test_ner_reactivable(self, env) -> None:
        env(enable_ml_models="true", intent_model_kind="lstm", enable_ner_model="true")
        _, ner = factory.load_ml_predictors()
        assert isinstance(ner, NERPredictor)
        assert isinstance(factory.load_ner_predictor(), NERPredictor)

    @pytest.mark.skipif(not LSTM_OK, reason="checkpoint lstm absent")
    def test_repli_lstm(self, env, tmp_path) -> None:
        env(intent_model_kind="head", intent_head_path=str(tmp_path / "absent.joblib"))
        assert type(factory.load_intent_predictor()) is IntentPredictor
        assert factory.load_intent_predictor(fallback=False) is None

    @pytest.mark.skipif(not LSTM_OK, reason="checkpoint lstm absent")
    def test_choix_explicite_labo(self, env) -> None:
        env(intent_model_kind="head")
        assert type(factory.load_intent_predictor("lstm")) is IntentPredictor


class TestPartageEncodeur:
    """un seul mpnet en mémoire."""

    def test_partage(self, monkeypatch) -> None:
        # registre vide, pas de fuite
        monkeypatch.setattr(embeddings, "_ST_MODELS", {})
        emb = SentenceTransformerEmbedder(model_name=ENCODER_NAME)
        retriever = VectorRetriever(embedder=emb)
        enc = object()
        assert factory.share_encoder(retriever, SimpleNamespace(encoder=enc))
        assert emb._model is enc
        # déjà chargé : on ne touche pas
        assert not factory.share_encoder(retriever, SimpleNamespace(encoder=object()))
        assert emb._model is enc

    def test_pas_de_partage(self) -> None:
        autre = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
        assert not factory.share_encoder(
            VectorRetriever(embedder=autre), SimpleNamespace(encoder=1)
        )
        assert autre._model is None
        emb = SentenceTransformerEmbedder(model_name=ENCODER_NAME)
        # lstm : pas d'encodeur
        assert not factory.share_encoder(VectorRetriever(embedder=emb), SimpleNamespace())
        assert not factory.share_encoder(VectorRetriever(embedder=emb), None)
        assert emb._model is None
