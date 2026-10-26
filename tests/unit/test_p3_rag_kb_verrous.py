"""KB : verrou à l'ajout, batch, traces de suppression."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag.knowledge_base import KnowledgeBase
from jenny.rag.vector_store import NOT_TOMBSTONE_SQL, TOMBSTONE_KEY

BID = str(uuid4())
ROOT = Path(__file__).resolve().parents[2]


class _Emb:
    max_tokens = 128
    dimension = 4

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class _Db:
    """Table en mémoire, journal SQL."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.log: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if "pg_advisory" in sql:
            kind = "shared" if "_shared" in sql else "excl"
            self.log.append(f"lock:{kind}:{params['key']}")
            return SimpleNamespace()
        if sql.startswith("INSERT") and "NOT EXISTS" in sql:
            self.log.append("tombstone")
            meta = json.loads(params["metadata"])
            if not any(r["metadata"].get(TOMBSTONE_KEY) == params["key"] for r in self.rows):
                self.rows.append(
                    {"content": "", "metadata": meta, "embedding": None, "chunk_index": 0}
                )
            return SimpleNamespace(rowcount=1)
        if sql.startswith("INSERT"):
            self.log.append("insert")
            self.rows.append(
                {
                    "content": params["content"],
                    "metadata": json.loads(params["metadata"]),
                    "embedding": params["embedding"],
                    "chunk_index": params["chunk_index"],
                }
            )
            return SimpleNamespace(rowcount=1)
        if sql.startswith("DELETE"):
            self.log.append("delete")
            kid = params["knowledge_id"]
            before = len(self.rows)
            self.rows = [r for r in self.rows if r["metadata"].get("knowledge_id") != kid]
            return SimpleNamespace(rowcount=before - len(self.rows))
        if sql.startswith("SELECT content, metadata_, chunk_index"):
            mine = [
                SimpleNamespace(
                    content=r["content"], metadata_=r["metadata"], chunk_index=r["chunk_index"]
                )
                for r in self.rows
                if r["metadata"].get("knowledge_id") == params["knowledge_id"]
            ]
            return SimpleNamespace(fetchall=lambda: mine)
        if sql.startswith(f"SELECT DISTINCT metadata_->>'{TOMBSTONE_KEY}'"):
            keys = [
                SimpleNamespace(key=r["metadata"][TOMBSTONE_KEY])
                for r in self.rows
                if r["metadata"].get(TOMBSTONE_KEY)
            ]
            return SimpleNamespace(fetchall=lambda: keys)
        raise AssertionError(sql)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _kb(db: _Db) -> KnowledgeBase:
    return KnowledgeBase(business_id=BID, session=db, embedder=_Emb())


@pytest.mark.asyncio
async def test_ajout_bloque_pendant_un_seed() -> None:
    db = _Db()
    entry = await _kb(db).add_text("Ouvert le mardi.", title="Horaires", category="horaires")
    # verrou partagé du salon avant l'écriture
    assert db.log[:3] == [
        f"lock:shared:jenny:kb:{BID}",
        f"lock:excl:jenny:kb:{BID}:{entry.id}",
        "insert",
    ]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_suppression_fiche_generee_laisse_une_trace() -> None:
    db = _Db()
    kb = _kb(db)
    entry = await kb.add_text(
        "Liste d'attente possible.",
        title="Liste d'attente",
        category="rendez-vous",
        metadata={"kb_key": "liste-attente", "seed": "kb_coiffeur_reel"},
    )
    assert await kb.delete_entry(entry.id)
    assert await kb.tombstones() == {"liste-attente"}
    trace = next(r for r in db.rows if r["metadata"].get(TOMBSTONE_KEY))
    # jamais trouvée par la recherche
    assert trace["embedding"] is None and trace["content"] == ""
    assert "knowledge_id" not in trace["metadata"]


@pytest.mark.asyncio
async def test_suppression_sans_trace() -> None:
    db = _Db()
    kb = _kb(db)
    owner = await kb.add_text("Ma fiche à moi.", title="Perso")
    ours = await kb.add_text(
        "Rappel la veille.", title="Rappels", metadata={"kb_key": "rappels", "seed": "x"}
    )
    await kb.delete_entry(owner.id)
    # la synchro retire sans trace
    await kb.delete_entry(ours.id, tombstone=False)
    assert "tombstone" not in db.log
    assert await kb.tombstones() == set()


@pytest.mark.asyncio
async def test_batch_un_verrou_un_commit() -> None:
    db = _Db()
    kb = _kb(db)
    async with kb.batch():
        a = await kb.add_text("Un.", title="A")
        async with kb.batch():
            # imbriqué : rien de plus
            await kb.add_text("Deux.", title="B")
        await kb.delete_entry(a.id, tombstone=False)
        assert db.commits == 0
    assert db.commits == 1
    assert db.log[0] == f"lock:excl:jenny:kb:{BID}"
    assert db.log.count(f"lock:excl:jenny:kb:{BID}") == 1


@pytest.mark.asyncio
async def test_batch_erreur_tout_annule() -> None:
    db = _Db()
    kb = _kb(db)
    with pytest.raises(RuntimeError):
        async with kb.batch():
            await kb.add_text("Un.", title="A")
            raise RuntimeError("boom")
    assert db.commits == 0 and db.rollbacks == 1
    # le kb reste utilisable
    await kb.add_text("Deux.", title="B")
    assert db.commits == 1


@pytest.mark.asyncio
async def test_batch_sans_commit_pour_le_script() -> None:
    db = _Db()
    kb = _kb(db)
    async with kb.batch(commit=False):
        await kb.add_text("Un.", title="A")
    assert db.commits == 0


def test_reindex_ignore_les_traces() -> None:
    spec = importlib.util.spec_from_file_location("reindex_kb_p3", ROOT / "scripts" / "reindex_kb.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["reindex_kb_p3"] = mod
    spec.loader.exec_module(mod)

    class _S:
        sql = ""

        async def execute(self, stmt, params=None):
            _S.sql = str(stmt)
            return SimpleNamespace(all=lambda: [])

    import asyncio

    asyncio.run(mod._rows(_S(), None))
    assert NOT_TOMBSTONE_SQL in _S.sql
    asyncio.run(mod._rows(_S(), BID))
    assert NOT_TOMBSTONE_SQL in _S.sql and "business_id = :bid" in _S.sql
