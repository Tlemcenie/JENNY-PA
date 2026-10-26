"""Moteur de prod : un seul mpnet pour le RAG et l'intention."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from jenny.core.config import Settings, get_settings
from jenny.engine import factory
from jenny.engine.conversation_engine import EngineRequest
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder

# chemin de prod (joblib ou npz)
HEAD = Path(Settings.model_fields["intent_head_path"].default)

pytestmark = [
    pytest.mark.real_embedder,
    pytest.mark.skipif(not HEAD.exists(), reason="checkpoint tête absent"),
]


@pytest.fixture
def prod_settings(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Réglages ML de la prod."""
    monkeypatch.setenv("JENNY_ENABLE_ML_MODELS", "true")
    monkeypatch.setenv("JENNY_INTENT_MODEL_KIND", "head")
    monkeypatch.setenv("JENNY_ENABLE_NER_MODEL", "false")
    get_settings.cache_clear()
    # registre vierge, sans fuite
    monkeypatch.setattr(embeddings, "_ST_MODELS", {})
    factory.reset_engine()
    yield
    get_settings.cache_clear()
    factory.reset_engine()


async def test_build_engine_partage_mpnet(prod_settings, db_tables, monkeypatch) -> None:
    """build_engine : un mpnet, vrai tour."""
    engine = factory.build_engine()
    head = engine.intent_predictor
    encoder = getattr(head, "encoder", None)
    if encoder is None:
        pytest.skip("tête indisponible (modèle HF absent du cache ?)")
    emb = engine.retriever.embedder
    # vrai singleton de prod
    assert type(emb) is SentenceTransformerEmbedder
    assert emb is embeddings.get_default_embedder()
    assert emb._model is encoder
    assert list(embeddings._ST_MODELS.values()) == [encoder]

    calls: list[object] = []
    real_encode = encoder.encode

    def _spy(texts, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(texts)
        return real_encode(texts, *args, **kwargs)

    monkeypatch.setattr(encoder, "encode", _spy)
    resp = await engine.process(
        EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Vous êtes ouverts le samedi ?",
            channel="whatsapp",
        )
    )
    assert resp.response_text
    # l'intention a encodé
    assert calls
    n = len(calls)
    # rag : même objet modèle
    vec = await emb.embed_query("Vous faites des balayages ?")
    assert len(calls) == n + 1
    assert len(vec) == 768
    direct = real_encode("Vous faites des balayages ?", convert_to_numpy=True)
    assert np.allclose(vec, direct, atol=1e-5)
    # toujours un seul modèle
    assert list(embeddings._ST_MODELS.values()) == [encoder]
