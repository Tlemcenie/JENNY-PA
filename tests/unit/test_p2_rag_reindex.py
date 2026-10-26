"""Réindexation sûre pendant que l'app écrit."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag.knowledge_base import KnowledgeBase

ROOT = Path(__file__).resolve().parents[2]
BID = str(uuid4())


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # requis par @dataclass
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


reindex = _load(ROOT / "scripts" / "reindex_kb.py", "reindex_kb")


class _Emb:
    """Faux encodeur, 1 mot = 1 token."""

    max_tokens = 128
    dimension = 4

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_passages(texts)


def _row(kid: str, content: str, idx: int = 0, **meta):
    return SimpleNamespace(
        id=uuid4(),
        business_id=BID,
        content=content,
        source="text",
        chunk_index=idx,
        metadata_=json.dumps({"knowledge_id": kid, "title": "T", "category": "faq", **meta}),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class _Db:
    """Table + transactions, en mémoire."""

    def __init__(self, rows) -> None:
        self.committed = list(rows)
        self.work = list(rows)
        self.locks: list[str] = []
        self.commits = 0
        # appelé quand on prend le verrou
        self.on_lock = None
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    def kid_of(self, r) -> str:
        return json.loads(r.metadata_)["knowledge_id"]

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "pg_advisory" in sql:
            self.locks.append(params["key"])
            if "_shared" not in sql and self.on_lock:
                # écriture de l'app, déjà commitée
                hook, self.on_lock = self.on_lock, None
                hook(self)
            return SimpleNamespace()
        if sql.lstrip().startswith("SELECT"):
            if ":kid" in sql:
                rows = [r for r in self.work if self.kid_of(r) == params["kid"]]
            else:
                rows = list(self.work)
            rows.sort(key=lambda r: (r.chunk_index, str(r.id)))
            return SimpleNamespace(all=lambda: rows)
        if sql.lstrip().startswith("DELETE"):
            ids = set(params["ids"])
            before = len(self.work)
            self.work = [r for r in self.work if r.id not in ids]
            return SimpleNamespace(rowcount=before - len(self.work))
        if "INSERT INTO document_embeddings" in sql:
            self.work.append(
                SimpleNamespace(
                    id=uuid4(),
                    business_id=params["business_id"],
                    content=params["content"],
                    source=params["source"],
                    chunk_index=params["chunk_index"],
                    metadata_=params["metadata"],
                    created_at=params["created_at"],
                )
            )
            return SimpleNamespace(rowcount=1)
        if sql.lstrip().startswith("UPDATE"):
            return SimpleNamespace(rowcount=1)
        raise AssertionError(sql)

    async def commit(self) -> None:
        self.committed = list(self.work)
        self.commits += 1

    async def rollback(self) -> None:
        self.work = list(self.committed)

    # écritures de l'app (commitées)

    def app_delete(self, kid: str) -> None:
        self.committed = [r for r in self.committed if self.kid_of(r) != kid]
        self.work = list(self.committed)

    def app_replace(self, kid: str, content: str) -> None:
        self.app_delete(kid)
        self.committed.append(_row(kid, content))
        self.work = list(self.committed)


def _contents(db: _Db, kid: str) -> list[str]:
    return [r.content for r in db.committed if db.kid_of(r) == kid]


@pytest.mark.asyncio
async def test_rechunk_normal() -> None:
    db = _Db([_row("a", "Ouvert le mardi."), _row("b", "Fermé le lundi.")])
    rep = await reindex.rechunk(db, _Emb(), list(db.committed))
    assert rep.done == 2 and not rep.gone and not rep.busy
    assert _contents(db, "a") == ["Ouvert le mardi."]
    # un commit par entrée
    assert db.commits == 2
    assert f"jenny:kb:{BID}:a" in db.locks


@pytest.mark.asyncio
async def test_entree_supprimee_pendant_le_run_ne_revient_pas() -> None:
    db = _Db([_row("a", "Ouvert le mardi."), _row("b", "Fermé le lundi.")])
    snapshot = list(db.committed)
    db.on_lock = lambda d: d.app_delete("a")
    rep = await reindex.rechunk(db, _Emb(), snapshot)
    assert rep.gone == ["a"]
    assert _contents(db, "a") == []
    assert _contents(db, "b") == ["Fermé le lundi."]


@pytest.mark.asyncio
async def test_entree_editee_pendant_le_run_pas_de_doublon() -> None:
    db = _Db([_row("a", "Coupe femme : 35 €.")])
    snapshot = list(db.committed)
    db.on_lock = lambda d: d.app_replace("a", "Coupe femme : 39 €.")
    rep = await reindex.rechunk(db, _Emb(), snapshot)
    # nouveau texte seul, redécoupé
    assert _contents(db, "a") == ["Coupe femme : 39 €."]
    assert rep.done == 1 and not rep.busy


@pytest.mark.asyncio
async def test_entree_editee_sans_arret_abandonnee() -> None:
    db = _Db([_row("a", "v1")])
    snapshot = list(db.committed)
    n = {"v": 1}

    def edit(d: _Db) -> None:
        n["v"] += 1
        d.app_replace("a", f"v{n['v']}")
        d.on_lock = edit

    db.on_lock = edit
    rep = await reindex.rechunk(db, _Emb(), snapshot)
    assert rep.busy == ["a"]
    # dernière version de l'app gardée
    assert _contents(db, "a") == [f"v{n['v']}"]


@pytest.mark.asyncio
async def test_dry_run_n_ecrit_rien() -> None:
    rows = [_row("a", "Ouvert le mardi.")]
    db = _Db(rows)
    rep = await reindex.rechunk(db, _Emb(), list(rows), dry_run=True)
    assert rep.done == 1
    assert [r.id for r in db.committed] == [r.id for r in rows]
    assert db.commits == 0


@pytest.mark.asyncio
async def test_suppression_partielle_annule() -> None:
    db = _Db([_row("a", "Un.", 0), _row("a", "Deux.", 1)])
    snapshot = list(db.committed)
    real = db.execute

    async def half_delete(stmt, params=None):
        res = await real(stmt, params)
        if str(stmt).lstrip().startswith("DELETE"):
            return SimpleNamespace(rowcount=res.rowcount - 1)
        return res

    db.execute = half_delete
    rep = await reindex.rechunk(db, _Emb(), snapshot)
    assert rep.busy == ["a"]
    assert sorted(_contents(db, "a")) == ["Deux.", "Un."]


# l'app prend le même verrou


class _Store:
    def __init__(self, db: _Db) -> None:
        self.db = db

    async def entry_chunks(self, _s, _b, kid):
        return [
            (r.content, json.loads(r.metadata_)) for r in self.db.work if self.db.kid_of(r) == kid
        ]

    async def delete_by_knowledge_id(self, _s, _b, kid):
        before = len(self.db.work)
        self.db.work = [r for r in self.db.work if self.db.kid_of(r) != kid]
        return before - len(self.db.work)

    async def add_chunks(self, _s, _b, chunks):
        return len(chunks)


@pytest.mark.asyncio
async def test_app_verrouille_avant_de_lire() -> None:
    db = _Db([_row("k", "Ouvert le mardi.")])
    kb = KnowledgeBase(business_id=BID, session=db, embedder=_Emb(), vector_store=_Store(db))
    await kb.update_text_entry("k", "Ouvert le mercredi.", title="T", category="faq")
    assert db.locks[:2] == [f"jenny:kb:{BID}", f"jenny:kb:{BID}:k"]
    await kb.delete_entry("k")
    assert db.locks[-1] == f"jenny:kb:{BID}:k"


def test_fingerprint_change_si_ids_changent() -> None:
    a = _row("a", "x")
    b = _row("a", "x")
    assert reindex.fingerprint([a]) == reindex.fingerprint([a])
    assert reindex.fingerprint([a]) != reindex.fingerprint([b])
