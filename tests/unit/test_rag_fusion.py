"""Recherche hybride : RRF, seuil avant top_k, erreurs non silencieuses."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from jenny.rag import vector_store as vs
from jenny.rag.rerank import blend, fusion_key, lexical_score, rerank, rrf
from jenny.rag.retriever import VectorRetriever
from jenny.rag.vector_store import PgVectorStore, VectorSearchError, build_tsquery


@dataclass
class _Row:
    id: str
    content: str
    vscore: float
    trank: float | None = None
    source: str = "text"
    metadata_: dict = field(default_factory=dict)
    created_at: object = None


class _Result:
    def __init__(self, rows=None, one=None) -> None:
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def one(self):
        return self._one


class _Bind:
    def __init__(self, name: str) -> None:
        self.dialect = type("D", (), {"name": name})()
        self.url = f"{name}://test-{id(self)}"


class _FakeSession:
    """Session pgvector simulée."""

    def __init__(self, rows, dialect: str = "postgresql", fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail
        self.sql: list[str] = []
        self.params: list[dict] = []
        self._bind = _Bind(dialect)

    def get_bind(self):
        return self._bind

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        self.params.append(params or {})
        if "information_schema" in sql:
            caps = type("C", (), {"fts": True, "cfg": True, "vver": "0.8.2"})()
            return _Result(one=caps)
        if "set_config" in sql:
            return _Result()
        if self.fail:
            raise RuntimeError("pgvector en panne")
        return _Result(rows=self.rows)


@pytest.fixture(autouse=True)
def _reset_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vs, "_CAPS", {})


def test_rrf_favorise_le_consensus() -> None:
    fused = rrf([["a", "b", "c"], ["b", "c", "a"]])
    assert max(fused, key=fused.get) == "b"
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_fusion_key_modes() -> None:
    assert fusion_key(0.5, 0.0, 1.0, "score") == 0.5
    assert fusion_key(0.5, 0.5, 1.0, "rrf") > fusion_key(0.9, 0.4, 1.0, "rrf")
    assert fusion_key(0.5, 1.0, 1.0, "mix") == pytest.approx(0.6)


def test_build_tsquery_propre_et_synonymes() -> None:
    q = build_tsquery("Je peux décommander l'RDV sans pénalité ?! (urgent)")
    words = q.split(" | ")
    assert words[:3] == ["decommander", "rdv", "penalite"]
    assert "annulation" in words  # synonyme
    assert all(w.isalnum() for w in words)
    assert build_tsquery("bonjour merci") == ""


def test_lexical_score_flexions_et_synonymes() -> None:
    doc = "La coupe femme comprend le shampoing ; le brushing est en supplément."
    assert lexical_score("Le brushing est inclus avec la coupe ?", doc) == 1.0
    assert lexical_score("Vous faites des extensions ?", doc) == 0.0


def test_fuse_mix_remonte_le_bon_doc() -> None:
    rows = [
        _Row("b", "Nos horaires : du mardi au samedi.", vscore=0.66),
        _Row("a", "La coupe femme comprend le brushing.", vscore=0.60, trank=0.2),
    ]
    docs = PgVectorStore._fuse(rows, "Le brushing est compris dans la coupe ?")
    assert [d.id for d in docs] == ["a", "b"]
    assert docs[0].score == pytest.approx(blend(0.60, 1.0))
    assert docs[0].vector_score == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_search_seuil_avant_top_k() -> None:
    rows = [
        _Row("1", "Coupe femme : 39 €.", vscore=0.90),
        _Row("2", "Parking à 200 m.", vscore=0.10),
        _Row("3", "Coupe homme : 25 €.", vscore=0.85),
        _Row("4", "Wi-Fi gratuit.", vscore=0.20),
    ]
    session = _FakeSession(rows)
    docs = await PgVectorStore().search(
        session, uuid4(), [0.1] * 4, top_k=2, score_threshold=0.5, query_text="prix coupe"
    )
    assert {d.id for d in docs} == {"1", "3"}
    assert all(d.score >= 0.5 for d in docs)
    # requête hybride + scan HNSW itératif
    assert any("to_tsquery" in s for s in session.sql)
    assert any("set_config" in s for s in session.sql)


@pytest.mark.asyncio
async def test_search_filtre_toujours_par_business() -> None:
    session = _FakeSession([])
    bid = uuid4()
    await PgVectorStore().search(session, bid, [0.0] * 4, query_text="coupe")
    main = session.sql[-1]
    assert main.count("business_id = :business_id") >= 2
    assert session.params[-1]["business_id"] == str(bid)


@pytest.mark.asyncio
async def test_caps_en_cache() -> None:
    session = _FakeSession([])
    store = PgVectorStore()
    await store.search(session, uuid4(), [0.0] * 4, query_text="coupe")
    await store.search(session, uuid4(), [0.0] * 4, query_text="coupe")
    assert sum("information_schema" in s for s in session.sql) == 1


@pytest.mark.asyncio
async def test_erreur_pas_silencieuse() -> None:
    session = _FakeSession([], fail=True)
    with pytest.raises(VectorSearchError):
        await PgVectorStore().search(session, uuid4(), [0.0] * 4, query_text="coupe")


@pytest.mark.asyncio
async def test_sqlite_renvoie_vide_sans_sql() -> None:
    session = _FakeSession([], dialect="sqlite")
    assert await PgVectorStore().search(session, uuid4(), [0.0] * 4) == []
    assert session.sql == []


class _Emb:
    dimension = 4

    async def embed_text(self, text: str) -> list[float]:
        return [0.1] * 4


def _factory(session):
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


@pytest.mark.asyncio
async def test_retriever_degrade_sans_crash() -> None:
    session = _FakeSession([], fail=True)
    retriever = VectorRetriever(_Emb(), PgVectorStore(), session_factory=_factory(session))
    assert await retriever.search("coupe", business_id=uuid4()) == []


@pytest.mark.asyncio
async def test_retriever_hybride_et_seuil() -> None:
    rows = [
        _Row("1", "Coupe femme : 39 €.", vscore=0.9, metadata_={"title": "Coupe femme"}),
        _Row("2", "Parking à 200 m.", vscore=0.1),
    ]
    session = _FakeSession(rows)
    retriever = VectorRetriever(_Emb(), PgVectorStore(), session_factory=_factory(session))
    hits = await retriever.search("prix coupe femme", business_id=uuid4(), score_threshold=0.4)
    assert [h.id for h in hits] == ["1"]
    assert hits[0].metadata["title"] == "Coupe femme"


def test_rerank_compat_objets_du_banc() -> None:
    @dataclass
    class Hit:
        content: str
        score: float
        metadata: dict = field(default_factory=dict)

    hits = [Hit("Fermé le lundi.", 0.5), Hit("Ouvert le samedi de 9h à 18h.", 0.5)]
    out = rerank("Vous êtes ouverts le samedi ?", hits, 1)
    assert out[0].content.startswith("Ouvert le samedi")
