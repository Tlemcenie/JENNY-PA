"""Encodeur : singleton thread-safe, modèle partagé, cache des questions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from jenny.rag import embeddings as emb_mod


class _Tok:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(range(len(text.split())))


class _FakeModel:
    max_seq_length = 128

    def __init__(self) -> None:
        self.inputs: list = []
        self.tokenizer = _Tok()

    def get_embedding_dimension(self) -> int:
        return 3

    def encode(self, x, convert_to_numpy: bool = True, batch_size: int | None = None):
        self.inputs.append(x)
        if isinstance(x, str):
            return np.zeros(3)
        return np.zeros((len(x), 3))


@pytest.fixture(autouse=True)
def _clean_cache():
    emb_mod.reset_default_embedder()
    yield
    emb_mod.reset_default_embedder()


def test_default_embedder_meme_instance() -> None:
    assert emb_mod.get_default_embedder() is emb_mod.get_default_embedder()


def test_default_embedder_thread_safe() -> None:
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(lambda _: emb_mod.get_default_embedder(), range(32)))
    assert len({id(e) for e in got}) == 1


@pytest.mark.asyncio
async def test_modele_partage_et_cache_question(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeModel()
    monkeypatch.setitem(emb_mod._ST_MODELS, "fake-model", fake)
    e1 = emb_mod.SentenceTransformerEmbedder("fake-model")
    e2 = emb_mod.SentenceTransformerEmbedder("fake-model")
    await e1.embed_query("bonjour")
    await e1.embed_query("bonjour")
    # 2e appel servi par le cache
    assert fake.inputs == ["bonjour"]
    await e2.embed_batch(["a", "b"])
    assert e2._model is fake
    assert e1.max_tokens == 128
    assert e1.count_tokens("un deux trois") == 3


@pytest.mark.asyncio
async def test_prefixes_e5(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeModel()
    monkeypatch.setitem(emb_mod._ST_MODELS, "intfloat/multilingual-e5-base", fake)
    e = emb_mod.SentenceTransformerEmbedder("intfloat/multilingual-e5-base")
    await e.embed_query("horaires ?")
    await e.embed_passages(["Ouvert le mardi."])
    assert fake.inputs[0] == "query: horaires ?"
    assert fake.inputs[1] == ["passage: Ouvert le mardi."]


def test_fenetre_connue_sans_charger() -> None:
    e = emb_mod.SentenceTransformerEmbedder("paraphrase-multilingual-mpnet-base-v2")
    assert e.max_tokens == 128
    assert e.dimension == 768


def test_estimation_tokens() -> None:
    assert emb_mod.estimate_tokens("") == 0
    assert emb_mod.estimate_tokens("a" * 34) == 10
