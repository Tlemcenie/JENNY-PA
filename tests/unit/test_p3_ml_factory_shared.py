"""mpnet partagé : un objet, sûr entre threads."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from jenny.core.config import get_settings
from jenny.engine import factory
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder
from ml.models.intent_head import predict as head_predict
from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor

HEAD_OK = Path("checkpoints/intent_head/head.npz").exists()

TEXTES = [
    "Je voudrais un rdv samedi et vous prenez la CB ?",
    "C'est combien une couleur ?",
    "mon colis n'est pas arrivé",
    "Vous avez de la place jeudi ?",
    "Merci, bonne journée",
    "jvoudrais une coupe demain 15h",
]


@pytest.fixture
def shared(monkeypatch):
    """vrai mpnet, via le rag."""
    if not HEAD_OK:
        pytest.skip("checkpoint tête absent")
    # mpnet déjà en ram : on reprend
    known = [
        e for (name, dev), e in head_predict._ENCODERS.items() if name == ENCODER_NAME and not dev
    ]
    registry = {ENCODER_NAME: known[0]} if known else {}
    monkeypatch.setattr(embeddings, "_ST_MODELS", registry)
    monkeypatch.setattr(head_predict, "_ENCODERS", {})
    emb = SentenceTransformerEmbedder(model_name=ENCODER_NAME)
    # conftest met un faux embedder
    monkeypatch.setattr(factory, "get_default_embedder", lambda: emb)
    try:
        head = factory.load_intent_predictor()
    except OSError as e:
        pytest.skip(f"encodeur indisponible : {e}")
    if head is None:
        pytest.skip("encodeur indisponible")
    yield head, emb
    get_settings.cache_clear()


class TestUnSeulMpnet:
    """le rag et la tête partagent."""

    def test_meme_objet(self, shared) -> None:
        head, emb = shared
        assert isinstance(head, EmbeddingIntentPredictor)
        assert isinstance(emb, SentenceTransformerEmbedder)
        assert head.encoder is emb._model
        # aucun 2e chargement
        assert head_predict._ENCODERS == {}
        assert sum(m is head.encoder for m in embeddings._ST_MODELS.values()) == 1

    def test_build_engine_un_seul(self, shared, monkeypatch) -> None:
        _, emb = shared
        monkeypatch.setenv("JENNY_ENABLE_ML_MODELS", "true")
        monkeypatch.setenv("JENNY_ENABLE_NER_MODEL", "false")
        get_settings.cache_clear()
        eng = factory.build_engine(llm_provider=None)
        assert eng.intent_predictor.encoder is emb._model
        assert eng.retriever.embedder._model is eng.intent_predictor.encoder

    def test_threads_rag_et_tete(self, shared) -> None:
        head, emb = shared
        model = emb._model
        ref_head = [head.predict_multi(t)["all_scores"] for t in TEXTES]
        ref_rag = model.encode(TEXTES, convert_to_numpy=True)
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def tete(k: int) -> None:
            barrier.wait()
            for _ in range(5):
                got = head.predict_multi(TEXTES[k % len(TEXTES)])["all_scores"]
                ref = ref_head[k % len(TEXTES)]
                assert all(abs(got[lab] - ref[lab]) < 1e-3 for lab in ref)

        def rag(k: int) -> None:
            barrier.wait()
            for _ in range(5):
                # chemin du rag : asyncio.to_thread
                vec = asyncio.run(emb.embed_text(TEXTES[k % len(TEXTES)]))
                assert np.allclose(vec, ref_rag[k % len(TEXTES)], atol=1e-4)

        with ThreadPoolExecutor(8) as pool:
            futs = [pool.submit(tete if k % 2 else rag, k) for k in range(8)]
            for f in futs:
                try:
                    f.result(timeout=120)
                except BaseException as e:
                    errors.append(e)
        assert errors == []


class TestCheckpointAbsent:
    """pas de mpnet pour rien."""

    def test_repli_sans_charger_mpnet(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("JENNY_INTENT_HEAD_PATH", str(tmp_path / "absent.npz"))
        get_settings.cache_clear()

        calls: list[int] = []
        monkeypatch.setattr(factory, "rag_encoder", lambda: calls.append(1))
        try:
            assert factory.load_intent_predictor() is None
        finally:
            get_settings.cache_clear()
        assert calls == []


class TestBoucleLibre:
    """build hors de la boucle."""

    def test_boucle_libre_pendant_build(self, monkeypatch) -> None:
        monkeypatch.setattr(factory, "_engine_singleton", None)
        started, release = threading.Event(), threading.Event()

        def slow() -> object:
            started.set()
            release.wait(5)
            return "moteur"

        monkeypatch.setattr(factory, "build_engine", slow)

        async def run() -> tuple[int, object]:
            task = asyncio.create_task(factory.aget_engine())
            await asyncio.to_thread(started.wait, 5)
            ticks = 0
            # la boucle tourne encore
            for _ in range(20):
                await asyncio.sleep(0)
                ticks += 1
            release.set()
            return ticks, await task

        ticks, eng = asyncio.run(run())
        assert ticks == 20 and eng == "moteur"
        factory.reset_engine()
