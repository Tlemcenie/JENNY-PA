"""réglages ml de la fabrique."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from jenny.core.config import Settings, get_settings
from jenny.engine import factory
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder
from jenny.rag.retriever import VectorRetriever
from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor

HEAD_OK = Path("checkpoints/intent_head/head.npz").exists()


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
    """valeurs par défaut."""

    def test_defauts(self) -> None:
        s = Settings(_env_file=None)
        assert s.intent_head_path == "checkpoints/intent_head/head.npz"


class TestChargement:
    """tête ou rien."""

    def test_ml_coupe(self, env) -> None:
        env(enable_ml_models="false")
        assert factory.load_intent_predictor() is None

    @pytest.mark.skipif(not HEAD_OK, reason="checkpoint tête absent")
    def test_tete(self, env) -> None:
        env(enable_ml_models="true")
        assert isinstance(factory.load_intent_predictor(), EmbeddingIntentPredictor)

    def test_checkpoint_absent(self, env, tmp_path) -> None:
        env(enable_ml_models="true", intent_head_path=str(tmp_path / "absent.npz"))
        assert factory.load_intent_predictor() is None


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
