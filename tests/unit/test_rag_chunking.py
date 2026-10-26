"""Découpage RAG : budget tokens, overlap, séparateurs, titre embarqué."""

from __future__ import annotations

from itertools import pairwise
from uuid import uuid4

import pytest

from jenny.rag.ingestion import DocumentIngester, build_embed_text, embed_header, reassemble
from jenny.rag.knowledge_base import KnowledgeBase


class _WordEmbedder:
    """1 mot = 1 token."""

    max_tokens = 40
    dimension = 4

    def __init__(self) -> None:
        self.seen: list[str] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def embed_text(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.seen += texts
        return await self.embed_batch(texts)


class _Bind:
    def __init__(self, name: str) -> None:
        self.dialect = type("D", (), {"name": name})()


class _Session:
    def __init__(self, name: str = "postgresql") -> None:
        self._bind = _Bind(name)

    def get_bind(self):
        return self._bind


def test_budget_tokens_respecte() -> None:
    ing = DocumentIngester(embedder=_WordEmbedder(), chunk_size=10_000)
    text = " ".join(f"Phrase numéro {i} sur le salon." for i in range(40))
    chunks = ing.chunk_text(text)
    budget = int(40 * 0.8)
    assert len(chunks) > 1
    assert all(len(c.content.split()) <= budget for c in chunks)


def test_budget_tient_compte_du_titre() -> None:
    ing = DocumentIngester(embedder=_WordEmbedder(), chunk_size=10_000)
    text = " ".join(f"Phrase {i} ici." for i in range(40))
    sans = ing.chunk_text(text)
    avec = ing.chunk_text(text, reserved_tokens=10)
    assert len(avec) > len(sans)
    assert all(len(c.content.split()) + 10 <= 32 for c in avec)


def test_overlap_reel() -> None:
    ing = DocumentIngester(embedder=_WordEmbedder(), chunk_size=10_000)
    text = " ".join(f"Phrase {i} ici." for i in range(60))
    chunks = ing.chunk_text(text)
    assert len(chunks) > 2
    for prev, nxt in pairwise(chunks):
        ov = nxt.metadata.get("overlap_chars")
        assert ov, "le fragment suivant doit reprendre la fin du précédent"
        assert prev.content.endswith(nxt.content[:ov])


def test_coupe_sur_lignes_puces_points_virgules() -> None:
    ing = DocumentIngester(chunk_size=40)
    text = (
        "Tarifs :\n- Coupe femme : 39 €\n- Coupe homme : 25 €\n"
        "• Brushing : 25 € ; Barbe : 15 € ; Soin : 20 €"
    )
    chunks = ing.chunk_text(text)
    assert all(len(c.content) <= 40 for c in chunks)
    # jamais de prix coupé en deux
    for item in ("Coupe femme : 39 €", "Coupe homme : 25 €", "Barbe : 15 €", "Soin : 20 €"):
        assert any(item in c.content for c in chunks), item


def test_sections_markdown_et_reassemble() -> None:
    text = "# Doc\n\n## Horaires\nOuvert du mardi au samedi.\n\n## Paiement\nCarte et espèces."
    chunks = DocumentIngester().chunk_text(text)
    assert [c.metadata.get("section") for c in chunks] == ["Horaires", "Paiement"]
    assert chunks[0].content.startswith("Horaires\n")
    back = reassemble([(c.content, c.metadata) for c in chunks])
    assert "Ouvert du mardi au samedi." in back
    assert "## Paiement" in back


def test_reassemble_retire_overlap() -> None:
    ing = DocumentIngester(chunk_size=80, chunk_overlap=30)
    text = " ".join(f"Phrase courte {i}." for i in range(15))
    chunks = ing.chunk_text(text)
    assert len(chunks) > 1
    back = reassemble([(c.content, c.metadata) for c in chunks])
    assert back.split() == text.split()


def test_compat_chunk_size_caracteres() -> None:
    ing = DocumentIngester(chunk_size=100, chunk_overlap=20)
    text = (
        "Jenny est une plateforme pour les salons. "
        "Elle gère les messages clients. "
        "Elle supporte Instagram, WhatsApp et email. "
        "Elle détecte les intentions. "
        "Les agents traitent chaque demande."
    )
    chunks = ing.chunk_text(text, metadata={"source": "test"})
    assert len(chunks) >= 2
    assert all(len(c.content) <= 100 for c in chunks)
    assert chunks[0].metadata["source"] == "test"


def test_titre_et_categorie_embarques() -> None:
    assert embed_header("Annulation", "politique") == "Annulation — Politique du salon"
    # libellé déjà dans le titre
    assert embed_header("Horaires d'ouverture", "horaires") == "Horaires d'ouverture"
    assert build_embed_text("x") == "x"
    assert build_embed_text("Ouvert à 9h.", "Horaires", "general") == "Horaires\nOuvert à 9h."


@pytest.mark.asyncio
async def test_prepare_chunks_vectorise_avec_le_titre() -> None:
    emb = _WordEmbedder()
    kb = KnowledgeBase(business_id=uuid4(), session=_Session(), embedder=emb)
    chunks = await kb.prepare_chunks(
        "Annulation gratuite jusqu'à 24 h avant.",
        knowledge_id="k1",
        title="Annuler un rendez-vous",
        category="politique",
        source="text",
        extra_metadata={"kb_key": "annulation-delai"},
    )
    assert emb.seen[0].startswith("Annuler un rendez-vous — Politique du salon\n")
    assert chunks[0]["content"] == "Annulation gratuite jusqu'à 24 h avant."
    meta = chunks[0]["metadata"]
    assert meta["kb_key"] == "annulation-delai"
    assert meta["knowledge_id"] == "k1"


@pytest.mark.asyncio
async def test_sans_pgvector_echoue_vite_sans_modele() -> None:
    class _Boom(_WordEmbedder):
        async def prepare(self) -> None:
            raise AssertionError("le modèle ne doit pas charger")

        async def embed_query(self, text: str) -> list[float]:
            raise AssertionError("pas d'embedding sans pgvector")

    kb = KnowledgeBase(business_id=uuid4(), session=_Session("sqlite"), embedder=_Boom())
    with pytest.raises(RuntimeError):
        await kb.add_text("Ouvert le mardi.", title="Horaires")
    assert await kb.search("horaires") == []
