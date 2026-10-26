"""Vieux fragments : pas de phrase en double."""

from __future__ import annotations

import re

from jenny.rag.ingestion import DocumentIngester, reassemble


def _old_chunks(text: str, size: int = 512, overlap: int = 50) -> list[tuple[str, dict]]:
    """Ancien découpage (code d'avant)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    cur: list[str] = []
    length = 0
    for s in sentences:
        if length + len(s) > size and cur:
            chunks.append(" ".join(cur))
            ov_text, ov = "", []
            for x in reversed(cur):
                if len(ov_text) + len(x) <= overlap:
                    ov.insert(0, x)
                    ov_text = " ".join(ov)
                else:
                    break
            cur, length = ov, len(ov_text)
        cur.append(s)
        length += len(s)
    if cur:
        chunks.append(" ".join(cur))
    return [
        (c, {"knowledge_id": "k", "title": "T", "chunk_index": i}) for i, c in enumerate(chunks)
    ]


LONG = " ".join(
    [
        "Le salon accueille les enfants dès trois ans avec un rehausseur adapté.",
        "Sur rendez-vous uniquement.",
        "Les colorations végétales demandent environ trente minutes de pose en plus.",
        "Merci de prévenir.",
        "Les poussettes peuvent entrer et un espace est prévu près de l'accueil du salon.",
        "Le paiement en trois fois est possible dès cent cinquante euros.",
        "Pensez à réserver.",
    ]
    * 3
)


def test_ancien_overlap_bien_reproduit() -> None:
    chunks = _old_chunks(LONG)
    assert len(chunks) >= 2
    # le défaut existe bien
    naive = "\n".join(c for c, _ in chunks)
    assert len(naive) > len(LONG) + 5


def test_reassemble_retire_la_phrase_doublee() -> None:
    rebuilt = reassemble(_old_chunks(LONG))
    # texte d'origine, au saut de ligne près
    assert rebuilt.replace("\n", " ") == LONG
    for s in set(re.split(r"(?<=[.!?])\s+", LONG)):
        assert rebuilt.count(s) == LONG.count(s), s


def test_nouveau_decoupage_inchange() -> None:
    text = "Ligne une.\nLigne deux.\n\nLigne une.\nFin."
    chunks = DocumentIngester(chunk_size=40).chunk_text(text)
    assert reassemble([(c.content, c.metadata) for c in chunks]) == text


def test_vieux_fragments_sans_repetition() -> None:
    old = [("Ligne un.", {"chunk_index": 0}), ("Ligne deux.", {"chunk_index": 1})]
    assert reassemble(old) == "Ligne un.\nLigne deux."
    # fragment = que la répétition : gardé
    same = [("Bonjour.", {"chunk_index": 0}), ("Bonjour.", {"chunk_index": 1})]
    assert reassemble(same) == "Bonjour.\nBonjour."
