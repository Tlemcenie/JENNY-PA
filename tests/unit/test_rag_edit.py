"""Édition KB : texte complet, rien perdu."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag.ingestion import DocumentIngester, reassemble
from jenny.rag.knowledge_base import PREVIEW_CHARS, KnowledgeBase, restore_preview_tail
from jenny.rag.vector_store import PgVectorStore

S1 = (
    "Toute annulation doit être faite au moins 24 heures avant le rendez-vous, "
    "par téléphone ou en ligne."
)
S2 = (
    "En cas d'absence sans prévenir, l'acompte versé lors de la réservation est conservé "
    "par le salon et une nouvelle réservation demandera obligatoirement un acompte de "
    "trente pour cent du montant total prévu."
)
S3 = "Après deux absences non signalées, la réservation en ligne sera bloquée pour ce compte."
LONG = f"{S1} {S2} {S3}"


class _Emb:
    """Faux encodeur, 1 mot = 1 token."""

    max_tokens = 128
    dimension = 4

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_batch(texts)


class _Session:
    """Session factice postgres."""

    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.commits = 0
        self.rollbacks = 0
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def execute(self, *_args, **_kwargs):
        return SimpleNamespace(fetchall=lambda: self.rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _MemStore:
    """Store en mémoire."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.deleted = 0

    async def entry_chunks(self, _session, _bid, kid):
        mine = [r for r in self.rows if r["metadata"]["knowledge_id"] == kid]
        mine.sort(key=lambda r: r["chunk_index"])
        return [(r["content"], {**r["metadata"], "chunk_index": r["chunk_index"]}) for r in mine]

    async def delete_by_knowledge_id(self, _session, _bid, kid):
        before = len(self.rows)
        self.rows = [r for r in self.rows if r["metadata"]["knowledge_id"] != kid]
        self.deleted += before - len(self.rows)
        return before - len(self.rows)

    async def add_chunks(self, _session, _bid, chunks):
        self.rows.extend(chunks)
        return len(chunks)


def _kb(store=None, session=None) -> KnowledgeBase:
    return KnowledgeBase(
        business_id=uuid4(), session=session or _Session(), embedder=_Emb(), vector_store=store
    )


async def _seed(kb: KnowledgeBase, store: _MemStore, content: str, **extra) -> str:
    chunks = await kb.prepare_chunks(
        content,
        knowledge_id="k1",
        title="Annulation",
        category="politique",
        source="text",
        extra_metadata=extra or None,
    )
    await store.add_chunks(None, kb.business_id, chunks)
    return "k1"


def _preview(content: str) -> str:
    """Même coupe que la route."""
    return content[:PREVIEW_CHARS] + "..." if len(content) > PREVIEW_CHARS else content


# découpage réversible


def test_reassemble_a_l_identique() -> None:
    chunks = DocumentIngester().chunk_text(LONG)
    assert len(chunks) > 1
    assert len(chunks[0].content) < PREVIEW_CHARS
    assert reassemble([(c.content, c.metadata) for c in chunks]) == LONG


def test_reassemble_garde_lignes_et_paragraphes() -> None:
    text = f"Tarifs :\n- Coupe femme : 39 €\n- Brushing : 25 €\n\n{S2} {S1}\n\n{S3}"
    chunks = DocumentIngester().chunk_text(text)
    assert len(chunks) > 1
    assert reassemble([(c.content, c.metadata) for c in chunks]) == text


def test_reassemble_vieux_fragments_sans_sep() -> None:
    # fragments d'avant le correctif
    old = [("Ligne un.", {"chunk_index": 0}), ("Ligne deux.", {"chunk_index": 1})]
    assert reassemble(old) == "Ligne un.\nLigne deux."


# liste : texte complet


@pytest.mark.asyncio
async def test_liste_rend_le_texte_complet() -> None:
    chunks = DocumentIngester().chunk_text(LONG)
    row = SimpleNamespace(
        knowledge_id="k1",
        title="Annulation",
        category="politique",
        source="text",
        contents=[c.content for c in chunks],
        metas=[json.dumps({"knowledge_id": "k1", **c.metadata}) for c in chunks],
        idx=list(range(len(chunks))),
        chunks_count=len(chunks),
        created_at=datetime.now(UTC),
    )
    kb = KnowledgeBase(
        business_id=uuid4(), session=_Session([row]), embedder=_Emb(), vector_store=PgVectorStore()
    )
    [entry] = await kb.list_entries()
    assert entry.content == LONG
    assert entry.chunks_count == len(chunks)


@pytest.mark.asyncio
async def test_apercu_route_montre_la_coupe() -> None:
    from jenny.api.routes.knowledge import _to_response

    chunks = DocumentIngester().chunk_text(LONG)
    row = SimpleNamespace(
        knowledge_id="k1",
        title="",
        category="politique",
        source="text",
        contents=[c.content for c in chunks],
        metas=[json.dumps(c.metadata) for c in chunks],
        idx=list(range(len(chunks))),
        chunks_count=len(chunks),
        created_at=datetime.now(UTC),
    )
    kb = KnowledgeBase(
        business_id=uuid4(), session=_Session([row]), embedder=_Emb(), vector_store=PgVectorStore()
    )
    [entry] = await kb.list_entries()
    # avant : 1re phrase seule, sans "..."
    assert _to_response(entry).content_preview.endswith("...")


# recollage de la fin cachée


def test_apercu_intact_rend_tout() -> None:
    assert restore_preview_tail(_preview(LONG), LONG) == LONG


def test_faute_corrigee_dans_l_apercu() -> None:
    edited = _preview(LONG).replace("téléphone", "telephone")
    assert restore_preview_tail(edited, LONG) == LONG.replace("téléphone", "telephone")


def test_mot_coupe_complete_sans_doublon() -> None:
    cut = LONG[:PREVIEW_CHARS]
    rest = LONG[PREVIEW_CHARS:]
    word_end = rest.split(" ", 1)[0]
    edited = cut + word_end + "..."
    assert restore_preview_tail(edited, LONG) == LONG


def test_texte_complet_renvoye_inchange() -> None:
    # futur front : texte entier
    new = LONG.replace("bloquée", "suspendue")
    assert restore_preview_tail(new, LONG) == new
    for shorter in (f"{S1} {S2}...", f"{S1}...", LONG[: PREVIEW_CHARS + 30] + "..."):
        assert restore_preview_tail(shorter, LONG) == shorter


def test_sans_points_ou_entree_courte() -> None:
    assert restore_preview_tail(LONG[:150], LONG) == LONG[:150]
    assert restore_preview_tail("Nouveau texte...", "court") == "Nouveau texte..."


def test_apercu_reecrit_pas_recolle() -> None:
    other = "Texte totalement différent sur les horaires du salon, ouvert du mardi au samedi..."
    assert restore_preview_tail(other, LONG) == other


# mise à jour


@pytest.mark.asyncio
async def test_maj_depuis_l_apercu_ne_perd_rien() -> None:
    store = _MemStore()
    kb = _kb(store)
    kid = await _seed(kb, store, LONG, kb_key="annulation-delai")
    [listed] = [await kb.get_entry(kid)]
    assert listed.content == LONG
    edited = _preview(listed.content).replace("24 heures", "48 heures")
    entry = await kb.update_text_entry(kid, edited, title="Annulation", category="politique")
    expected = LONG.replace("24 heures", "48 heures")
    assert entry is not None
    assert entry.content == expected
    after = await kb.get_entry(kid)
    assert after.content == expected
    assert after.metadata.get("kb_key") == "annulation-delai"


@pytest.mark.asyncio
async def test_maj_texte_complet() -> None:
    store = _MemStore()
    kb = _kb(store)
    kid = await _seed(kb, store, LONG)
    new = f"{S1}\n\n{S3}"
    entry = await kb.update_text_entry(kid, new, title="Annulation", category="politique")
    assert entry.content == new
    assert (await kb.get_entry(kid)).content == new


@pytest.mark.asyncio
async def test_maj_entree_absente() -> None:
    store = _MemStore()
    session = _Session()
    kb = _kb(store, session)
    assert await kb.update_text_entry("nope", "x", title="t") is None
    assert store.deleted == 0
    assert session.commits == 0


@pytest.mark.asyncio
async def test_maj_echec_vectorisation_n_efface_rien() -> None:
    class _Boom(_Emb):
        async def embed_passages(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("modèle HS")

    store = _MemStore()
    kb = _kb(store)
    kid = await _seed(kb, store, LONG)
    kb.embedder = _Boom()
    with pytest.raises(RuntimeError):
        await kb.update_text_entry(kid, "Nouveau texte.", title="Annulation")
    assert store.deleted == 0
    assert (await kb.get_entry(kid)).content == LONG
