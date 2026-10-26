"""Moteur de prod : un seul mpnet pour le RAG et l'intention."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from jenny.core.config import get_settings
from jenny.engine import factory
from jenny.engine.conversation_engine import EngineRequest
from jenny.rag import embeddings
from jenny.rag.embeddings import SentenceTransformerEmbedder

HEAD = Path("checkpoints/intent_head/head.joblib")

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
    if getattr(head, "encoder", None) is None:
        pytest.skip("tête indisponible (modèle HF absent du cache ?)")
    emb = engine.retriever.embedder
    # vrai singleton de prod
    assert type(emb) is SentenceTransformerEmbedder
    assert emb is embeddings.get_default_embedder()
    assert emb._model is head.encoder
    assert list(embeddings._ST_MODELS.values()) == [head.encoder]

    calls: list[str] = []
    real_query = emb.embed_query

    async def _spy(text: str) -> list[float]:
        calls.append(text)
        return await real_query(text)

    monkeypatch.setattr(emb, "embed_query", _spy)
    resp = await engine.process(
        EngineRequest(
            conversation_id=uuid4(),
            business_id=uuid4(),
            message_text="Vous êtes ouverts le samedi ?",
            channel="whatsapp",
        )
    )
    assert resp.response_text
    # le rag a bien encodé
    assert calls
    # toujours un seul modèle
    assert list(embeddings._ST_MODELS.values()) == [head.encoder]
    assert len(await real_query("Vous êtes ouverts le samedi ?")) == 768
