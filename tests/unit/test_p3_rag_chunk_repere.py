"""Fragments récents : repère, pas de retrait hérité."""

from __future__ import annotations

from jenny.rag.ingestion import CHUNK_VERSION, DocumentIngester, reassemble
from jenny.rag.knowledge_base import LAYOUT_KEYS

TEXT = (
    "Le salon accueille les enfants dès trois ans. Sur rendez-vous.\n"
    "Sur rendez-vous. Les colorations végétales demandent trente minutes."
)


def _chunks():
    return DocumentIngester(chunk_size=80).chunk_text(TEXT)


def test_cas_de_la_revue_bien_reproduit() -> None:
    chunks = _chunks()
    # ni overlap, ni sep, ni titre
    second = chunks[1]
    assert second.content.startswith("Sur rendez-vous. Les colorations")
    assert not {"overlap_chars", "sep", "section"} & set(second.metadata)
    # sans repère : la phrase saute
    bare = [(c.content, {k: v for k, v in c.metadata.items() if k != "chunk_v"}) for c in chunks]
    assert reassemble(bare) != TEXT


def test_fragment_recent_garde_sa_phrase() -> None:
    chunks = _chunks()
    assert all(c.metadata["chunk_v"] == CHUNK_VERSION for c in chunks)
    assert reassemble([(c.content, c.metadata) for c in chunks]) == TEXT


def test_repere_pas_expose_comme_meta() -> None:
    assert "chunk_v" in LAYOUT_KEYS


def test_vieux_fragments_toujours_nettoyes() -> None:
    prev = "Le salon accueille les enfants dès trois ans. Sur rendez-vous."
    old = [
        (prev, {"chunk_index": 0}),
        ("Sur rendez-vous. Les colorations végétales.", {"chunk_index": 1}),
    ]
    # ancien découpage : phrase recopiée
    assert reassemble(old) == prev + "\nLes colorations végétales."
