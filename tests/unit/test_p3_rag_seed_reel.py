"""Script seed : restauration des traces de suppression."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag.vector_store import TOMBSTONE_KEY

ROOT = Path(__file__).resolve().parents[2]
BID = uuid4()


def _load():
    spec = importlib.util.spec_from_file_location(
        "seed_kb_p3", ROOT / "scripts" / "seed_kb_coiffeur.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["seed_kb_p3"] = mod
    spec.loader.exec_module(mod)
    return mod


seed_mod = _load()


class _Db:
    def __init__(self) -> None:
        self.inserts: list[dict] = []
        self.tombstones: list[str] = []
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if sql.startswith("SELECT id FROM businesses"):
            return SimpleNamespace(scalar=lambda: BID)
        if "pg_advisory" in sql:
            return SimpleNamespace()
        if sql.startswith("SELECT id, content"):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
        if sql.startswith("DELETE"):
            return SimpleNamespace(rowcount=0)
        if sql.startswith("INSERT") and "NOT EXISTS" in sql:
            self.tombstones.append(params["key"])
            return SimpleNamespace(rowcount=1)
        if sql.startswith("INSERT"):
            self.inserts.append(params)
            return SimpleNamespace(rowcount=1)
        raise AssertionError(sql)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_restore_garde_les_traces_sans_vecteur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _salon(_s, _b):
        return {"id": BID, "name": "Salon", "slug": "salon"}, [], []

    monkeypatch.setattr(seed_mod, "load_salon", _salon)
    kid = str(uuid4())
    backup = {
        "business_id": str(BID),
        "rows": [
            {
                "id": str(uuid4()),
                "content": "Ouvert le mardi.",
                "source": "text",
                "chunk_index": 0,
                "metadata": {"knowledge_id": kid, "title": "Horaires", "category": "horaires"},
            },
            {
                "id": str(uuid4()),
                "content": "",
                "source": TOMBSTONE_KEY,
                "chunk_index": 0,
                "metadata": {TOMBSTONE_KEY: "liste-attente"},
            },
        ],
    }
    path = tmp_path / "in.json"
    path.write_text(json.dumps(backup))
    db = _Db()
    rep = await seed_mod.restore(db, "salon", path, backup_dir=tmp_path / "out")
    assert rep["entries"] == 1 and rep["inserted"] == 1
    # trace remise telle quelle
    assert db.tombstones == ["liste-attente"]
    assert all(json.loads(p["metadata"]).get(TOMBSTONE_KEY) is None for p in db.inserts)
