"""Fiche KB : texte complet + aperçu."""

from __future__ import annotations

from uuid import uuid4

from jenny.api.routes.knowledge import _to_response
from jenny.rag.knowledge_base import PREVIEW_CHARS, KnowledgeEntry


def test_full_content_and_preview() -> None:
    long = "Nous acceptons les annulations jusqu'à 24h avant. " * 12
    out = _to_response(KnowledgeEntry(business_id=str(uuid4()), content=long, category="politique"))
    assert out.content == long
    assert out.content_preview == long[:PREVIEW_CHARS] + "..."


def test_short_entry_same_text() -> None:
    out = _to_response(KnowledgeEntry(business_id=str(uuid4()), content="Ouvert le lundi."))
    assert out.content == out.content_preview == "Ouvert le lundi."
