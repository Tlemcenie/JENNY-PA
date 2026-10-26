"""Store : réglage du pool, erreurs propres, repli 'french'."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.core.config import get_settings
from jenny.rag import vector_store as vs
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


class _Session:
    """Session pgvector simulée."""

    def __init__(self, rows=None, *, cfg: bool = True, fail: Exception | None = None) -> None:
        self.rows = rows or []
        self.cfg = cfg
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self._bind = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"), url=f"pg://t-{id(self)}"
        )

    def get_bind(self):
        return self._bind

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "information_schema" in sql:
            caps = SimpleNamespace(fts=True, cfg=self.cfg, vver="0.8.2")
            return SimpleNamespace(one=lambda: caps)
        if "set_config" in sql:
            return SimpleNamespace()
        if self.fail:
            raise self.fail
        return SimpleNamespace(fetchall=lambda: self.rows)

    def search_params(self) -> dict:
        return next(p for s, p in self.calls if "embedding <=>" in s)


@pytest.fixture(autouse=True)
def _reset_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vs, "_CAPS", {})


async def _search(session, **kw):
    return await PgVectorStore().search(session, uuid4(), [0.1] * 4, query_text="prix coupe", **kw)


@pytest.mark.asyncio
async def test_pool_vient_du_reglage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", 47)
    s = _Session()
    await _search(s, top_k=3)
    assert s.search_params()["pool"] == 47


@pytest.mark.asyncio
async def test_pool_explicite_et_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", 17)
    s = _Session()
    await _search(s, top_k=3, pool_size=40)
    assert s.search_params()["pool"] == 40
    s = _Session()
    await _search(s, top_k=35)
    assert s.search_params()["pool"] == 35


@pytest.mark.parametrize("bad", [0, -3])
def test_pool_reglage_invalide_repli(monkeypatch: pytest.MonkeyPatch, bad: int) -> None:
    monkeypatch.setattr(get_settings(), "rag_rerank_candidates", bad)
    assert vs.default_pool() == vs.POOL_SIZE


@pytest.mark.asyncio
async def test_erreur_sans_sql_ni_parametres() -> None:
    boom = RuntimeError("[SQL: WITH vec AS (SELECT ...)] [parameters: {'business_id': 'x'}]")
    with pytest.raises(VectorSearchError) as exc:
        await _search(_Session(fail=boom), top_k=3)
    msg = str(exc.value)
    assert "SQL" not in msg and "parameters" not in msg
    assert "RuntimeError" in msg
    # détail gardé pour les logs
    assert exc.value.__cause__ is boom


def test_tsquery_accents_gardes_en_repli() -> None:
    folded = build_tsquery("Vous faites l'épilation des sourcils ?")
    assert "epilation" in folded.split(" | ")
    assert "épilation" not in folded
    raw = build_tsquery("Vous faites l'épilation des sourcils ?", keep_accents=True).split(" | ")
    assert "épilation" in raw and "epilation" in raw
    # pas de mots vides
    assert "vous" not in raw and "des" not in raw


@pytest.mark.asyncio
async def test_config_french_sans_unaccent() -> None:
    s = _Session(cfg=False)
    await PgVectorStore().search(
        s, uuid4(), [0.1] * 4, top_k=3, query_text="Prix du brushing élégant ?"
    )
    sql, params = next((q, p) for q, p in s.calls if "to_tsquery" in q)
    assert "to_tsquery('french'" in sql
    assert "élégant" in params["tsq"].split(" | ")


@pytest.mark.asyncio
async def test_seuil_avant_top_k_meme_avec_bonus_rrf() -> None:
    # 9 : sous le seuil, mais 1er en texte
    rows = [
        _Row("1", "Coupe femme : 39 €.", vscore=0.80, trank=0.3),
        _Row("2", "Soins et masques.", vscore=0.75),
        _Row("9", "Prix coupe, prix coupe.", vscore=0.25, trank=0.9),
        _Row("4", "Wi-Fi gratuit.", vscore=0.05),
    ]
    free = await PgVectorStore().search(
        _Session(rows), uuid4(), [0.1] * 4, top_k=2, score_threshold=0.0, query_text="prix coupe"
    )
    # sans seuil, le RRF le monte
    assert [d.id for d in free] == ["1", "9"]
    docs = await PgVectorStore().search(
        _Session(rows), uuid4(), [0.1] * 4, top_k=2, score_threshold=0.5, query_text="prix coupe"
    )
    # seuil d'abord : 2 docs valides
    assert [d.id for d in docs] == ["1", "2"]
