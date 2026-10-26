"""Comptage de tokens sûr entre threads."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from jenny.rag import embeddings as emb_mod
from jenny.rag.ingestion import DocumentIngester

MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def _real_tokenizer():
    """Vrai tokenizer rapide, sinon skip."""
    transformers = pytest.importorskip("transformers")
    try:
        return transformers.AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    except Exception:
        pytest.skip("tokenizer mpnet absent du cache")


class _StModel:
    """Comme SentenceTransformer, sans poids."""

    max_seq_length = 128

    def __init__(self, tok) -> None:
        self.tokenizer = tok

    def get_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts, **_kw):
        # même appel que sentence-transformers
        batch = [texts] if isinstance(texts, str) else list(texts)
        self.tokenizer(
            batch,
            padding=True,
            truncation="longest_first",
            return_tensors="pt",
            max_length=self.max_seq_length,
        )
        return np.zeros((len(batch), 3))


@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch):
    tok = _real_tokenizer()
    model = _StModel(tok)
    monkeypatch.setitem(emb_mod._ST_MODELS, "race-model", model)
    monkeypatch.setattr(emb_mod, "_COUNT_TOKENIZERS", {})
    return model


def _hammer(target, seconds: float, errors: list) -> threading.Thread:
    stop = time.monotonic() + seconds

    def run() -> None:
        while time.monotonic() < stop:
            try:
                target()
            except Exception as e:
                errors.append(repr(e))
                return

    return threading.Thread(target=run)


def test_compte_pendant_encode_sans_already_borrowed(shared) -> None:
    emb = emb_mod.SentenceTransformerEmbedder("race-model")
    long = ["Le salon est ouvert du mardi au samedi de 9h à 19h, sauf fériés. " * 6] * 48
    header = "Horaires d'ouverture — Horaires " * 3
    errors: list[str] = []
    threads = [_hammer(lambda: shared.encode(long), 2.0, errors) for _ in range(2)]
    threads += [_hammer(lambda: emb.count_tokens(header), 2.0, errors) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_compte_identique_au_tokenizer(shared) -> None:
    emb = emb_mod.SentenceTransformerEmbedder("race-model")
    text = "Coloration végétale : henné et plantes, sans ammoniaque ni oxydant."
    expected = len(shared.tokenizer.encode(text, add_special_tokens=False))
    assert emb.count_tokens(text) == expected
    # pas de troncature à 128
    big = "mot " * 400
    assert emb.count_tokens(big) == len(shared.tokenizer.encode(big, add_special_tokens=False))


def test_tokenizer_partage_jamais_modifie(shared) -> None:
    emb = emb_mod.SentenceTransformerEmbedder("race-model")
    shared.encode(["amorce"])
    before = shared.tokenizer.backend_tokenizer.truncation
    emb.count_tokens("un texte à compter")
    # réglage de l'encodeur intact
    assert shared.tokenizer.backend_tokenizer.truncation == before


class _SlowTok:
    """Tokenizer lent (pas rust)."""

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(range(len(text.split())))


class _Plain:
    max_seq_length = 128

    def __init__(self) -> None:
        self.tokenizer = _SlowTok()

    def get_embedding_dimension(self) -> int:
        return 3


def test_tokenizer_lent_copie_puis_verrou(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _Plain()
    monkeypatch.setitem(emb_mod._ST_MODELS, "slow-model", model)
    monkeypatch.setattr(emb_mod, "_COUNT_TOKENIZERS", {})
    emb = emb_mod.SentenceTransformerEmbedder("slow-model")
    assert emb.count_tokens("un deux trois") == 3
    tok, is_rust = emb_mod._counting_tokenizer("slow-model", model)
    assert not is_rust and tok is not model.tokenizer


def test_nouveau_modele_nouvelle_copie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb_mod, "_COUNT_TOKENIZERS", {})
    first, second = _Plain(), _Plain()
    a = emb_mod._counting_tokenizer("m", first)
    b = emb_mod._counting_tokenizer("m", second)
    assert a is not None and b is not None and a[0] is not b[0]


class _BoomEmb:
    """Comptage qui casse."""

    max_tokens = 128

    def count_tokens(self, text: str) -> int:
        raise RuntimeError("Already borrowed")


def test_ingester_compte_avec_repli() -> None:
    ing = DocumentIngester(embedder=_BoomEmb())
    assert ing.count_tokens("Horaires d'ouverture") == emb_mod.estimate_tokens(
        "Horaires d'ouverture"
    )
