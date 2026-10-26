"""fabrique : verrou, mpnet unique, ner."""

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jenny.core.config import Settings, get_settings
from jenny.engine import factory
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder
from jenny.rag.retriever import VectorRetriever
from ml.models.intent_head import predict as head_predict
from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor
from ml.models.ner.predict import NERPredictor

HEAD_OK = Path("checkpoints/intent_head/head.npz").exists()
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


class TestVerrou:
    """une seule construction."""

    def test_threads_un_seul_build(self, monkeypatch) -> None:
        monkeypatch.setattr(factory, "_engine_singleton", None)
        calls: list[int] = []

        def slow_build() -> object:
            calls.append(threading.get_ident())
            time.sleep(0.2)
            return object()

        monkeypatch.setattr(factory, "build_engine", slow_build)
        got: list[object] = []
        threads = [
            threading.Thread(target=lambda: got.append(factory.get_engine())) for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(calls) == 1
        assert len(got) == 8 and all(e is got[0] for e in got)
        factory.reset_engine()
        assert factory._engine_singleton is None

    def test_echec_puis_retente(self, monkeypatch) -> None:
        monkeypatch.setattr(factory, "_engine_singleton", None)
        state = {"n": 0}

        def flaky() -> object:
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("boom")
            return "moteur"

        monkeypatch.setattr(factory, "build_engine", flaky)
        with pytest.raises(RuntimeError):
            factory.get_engine()
        # pas de singleton cassé
        assert factory.get_engine() == "moteur"
        factory.reset_engine()

    def test_aget_engine_hors_boucle(self, monkeypatch) -> None:
        monkeypatch.setattr(factory, "_engine_singleton", None)
        main = threading.get_ident()
        seen: list[int] = []

        def build() -> object:
            seen.append(threading.get_ident())
            return "moteur"

        monkeypatch.setattr(factory, "build_engine", build)

        async def run() -> tuple[object, object]:
            # la boucle tourne pendant le build
            tick = asyncio.create_task(asyncio.sleep(0))
            first = await factory.aget_engine()
            await tick
            return first, await factory.aget_engine()

        first, second = asyncio.run(run())
        assert first == second == "moteur"
        assert seen and seen[0] != main
        assert len(seen) == 1
        factory.reset_engine()


class TestMpnetUnique:
    """head et rag : même objet."""

    @pytest.mark.skipif(not HEAD_OK, reason="checkpoint tête absent")
    def test_head_prend_le_mpnet_du_rag(self, monkeypatch, env) -> None:
        fake = SimpleNamespace(
            get_sentence_embedding_dimension=lambda: 768, max_seq_length=128, tokenizer=None
        )
        monkeypatch.setattr(embeddings, "_ST_MODELS", {ENCODER_NAME: fake})
        monkeypatch.setattr(head_predict, "_ENCODERS", {})
        emb = SentenceTransformerEmbedder(model_name=ENCODER_NAME)
        monkeypatch.setattr(factory, "get_default_embedder", lambda: emb)
        env(enable_ml_models="true", intent_model_kind="head")

        head = factory.load_intent_predictor("head", fallback=False)
        assert isinstance(head, EmbeddingIntentPredictor)
        assert head.encoder is fake
        # aucun 2e chargement
        assert head_predict._ENCODERS == {}
        retriever = VectorRetriever(embedder=emb)
        assert factory.share_encoder(retriever, head) is True
        assert emb._model is fake

    def test_rag_autre_modele(self, monkeypatch) -> None:
        autre = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
        monkeypatch.setattr(factory, "get_default_embedder", lambda: autre)
        assert factory.rag_encoder() is None

    def test_rag_pas_sentence_transformer(self, monkeypatch) -> None:
        monkeypatch.setattr(factory, "get_default_embedder", lambda: object())
        assert factory.rag_encoder() is None

    def test_chargement_concurrent_unique(self, monkeypatch) -> None:
        monkeypatch.setattr(embeddings, "_ST_MODELS", {})
        built: list[str] = []

        class SlowST:
            def __init__(self, name: str, **_kw: object) -> None:
                built.append(name)
                time.sleep(0.2)

            def get_sentence_embedding_dimension(self) -> int:
                return 768

        import sentence_transformers

        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", SlowST)
        emb = SentenceTransformerEmbedder(model_name=ENCODER_NAME)
        monkeypatch.setattr(factory, "get_default_embedder", lambda: emb)
        got: list[object] = []
        # warmup rag + fabrique
        t1 = threading.Thread(target=lambda: got.append(emb._load_model()))
        t2 = threading.Thread(target=lambda: got.append(factory.rag_encoder()))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert built == [ENCODER_NAME]
        assert got[0] is got[1]


class TestNerParDefaut:
    """le ner remplit les slots."""

    def test_defaut_actif(self, monkeypatch) -> None:
        monkeypatch.delenv("JENNY_ENABLE_NER_MODEL", raising=False)
        s = Settings(_env_file=None)
        assert s.enable_ner_model is True
        assert s.intent_head_path == "checkpoints/intent_head/head.npz"

    @pytest.mark.skipif(not (HEAD_OK and NER_OK), reason="checkpoints absents")
    def test_charge_avec_head(self, monkeypatch, env) -> None:
        monkeypatch.delenv("JENNY_ENABLE_NER_MODEL", raising=False)
        env(enable_ml_models="true", intent_model_kind="head")
        intent, ner = factory.load_ml_predictors()
        assert isinstance(intent, EmbeddingIntentPredictor)
        assert isinstance(ner, NERPredictor)

    def test_coupable(self, env) -> None:
        env(enable_ml_models="true", intent_model_kind="lstm", enable_ner_model="false")
        _, ner = factory.load_ml_predictors()
        assert ner is None
