"""seed_kb_coiffeur : garde-fous, sauvegarde, restauration."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag import kb_coiffeur as kc

ROOT = Path(__file__).resolve().parents[2]
BID = uuid4()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


seed_mod = _load(ROOT / "scripts" / "seed_kb_coiffeur.py", "seed_kb_coiffeur_p2")

BUSINESS = {
    "id": BID,
    "name": "Salon Réel",
    "slug": "salon-reel",
    "email": "",
    "phone": "",
    "description": "",
    "business_hours": {"tue": ["09:00", "19:00"], "sat": ["09:00", "17:00"]},
    "deposit_enabled": False,
    "deposit_percent": 30,
    "deposit_min_cents": 1000,
    "reminder_lead_minutes": 60,
    "day_reminder_lead_hours": 24,
    "loyalty_threshold": 0,
}
PRESTAS = [{"name": "Coupe femme", "duration_minutes": 45, "price_cents": 3900}]


def _row(content: str, title: str, seed: str | None = None, kid: str | None = None):
    meta = {"knowledge_id": kid or str(uuid4()), "title": title, "category": "faq"}
    if seed:
        meta["seed"] = seed
    return {
        "id": uuid4(),
        "content": content,
        "source": "text",
        "chunk_index": 0,
        "metadata_": json.dumps(meta),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


class _Db:
    """Session factice, journal des requêtes."""

    def __init__(self, rows, backup_dir: Path) -> None:
        self.rows = rows
        self.log: list[str] = []
        self.backup_dir = backup_dir
        self.inserted: list[dict] = []
        self.commits = 0
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if sql.startswith("SELECT id FROM businesses"):
            return SimpleNamespace(scalar=lambda: BID if params["s"] == BUSINESS["slug"] else None)
        if "pg_advisory" in sql:
            self.log.append("lock")
            return SimpleNamespace()
        if sql.startswith("SELECT DISTINCT metadata_->>'kb_tombstone'"):
            return SimpleNamespace(fetchall=lambda: [])
        if "AS knowledge_id" in sql:
            # list_entries : une ligne par fiche
            rows = []
            for r in self.rows:
                meta = json.loads(r["metadata_"])
                rows.append(
                    SimpleNamespace(
                        knowledge_id=meta["knowledge_id"],
                        title=meta.get("title"),
                        category=meta.get("category"),
                        source="text",
                        contents=[r["content"]],
                        metas=[r["metadata_"]],
                        idx=[0],
                        chunks_count=1,
                        created_at=r["created_at"],
                    )
                )
            return SimpleNamespace(fetchall=lambda: rows)
        if sql.startswith("SELECT id, content"):
            self.log.append("export")
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.rows))
        if sql.startswith("DELETE"):
            # sauvegarde déjà écrite ?
            self.log.append(f"delete:{len(list(self.backup_dir.glob('*.json')))}")
            self.last_delete = (sql, params)
            tag = params.get("tag")
            if tag:
                self.rows = [
                    r for r in self.rows if json.loads(r["metadata_"]).get("seed") != tag
                ]
            return SimpleNamespace(rowcount=1)
        if sql.startswith("INSERT"):
            self.inserted.append(params)
            return SimpleNamespace(rowcount=1)
        raise AssertionError(sql)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):
    async def _salon(_session, _bid):
        return dict(BUSINESS), list(PRESTAS), []

    monkeypatch.setattr(seed_mod, "load_salon", _salon)


def test_vrai_salon_refuse_sans_option() -> None:
    with pytest.raises(SystemExit, match="salon-reel"):
        seed_mod.check_target("mon-salon", salon_reel=False, force=False, dry_run=False)
    # l'ancien --force ne suffit plus
    with pytest.raises(SystemExit, match="--force ne suffit plus"):
        seed_mod.check_target("mon-salon", salon_reel=False, force=True, dry_run=False)
    with pytest.raises(SystemExit):
        seed_mod.check_target("demo", salon_reel=True, force=False, dry_run=False)
    seed_mod.check_target("demo", salon_reel=False, force=False, dry_run=False)
    seed_mod.check_target("mon-salon", salon_reel=True, force=False, dry_run=False)
    seed_mod.check_target("mon-salon", salon_reel=False, force=False, dry_run=True)


@pytest.mark.asyncio
async def test_vrai_salon_sauvegarde_avant_effacement(tmp_path: Path, patched) -> None:
    owner = _row("Nous fermons à 18h le samedi.", "Ouverture le samedi")
    old_seed = _row("Le salon se trouve au 14 rue des Tanneurs.", "Adresse du salon", kc.SEED_TAG)
    db = _Db([owner, old_seed], tmp_path)
    rep = await seed_mod.seed(db, "salon-reel", salon_reel=True, backup_dir=tmp_path)
    # export, puis delete (sauvegarde présente)
    assert db.log.index("export") < db.log.index("delete:1")
    assert db.log[db.log.index("export") - 1] == "lock"
    backup = json.loads(Path(rep["backup"]).read_text())
    assert {r["content"] for r in backup["rows"]} == {owner["content"], old_seed["content"]}
    # seules les fiches démo effacées
    sql, params = db.last_delete
    assert "metadata_->>'seed' =" in sql and params["tag"] == kc.SEED_TAG
    # fiche du gérant gardée, pas doublée
    assert rep["stats"]["kept_owner"] == 1
    metas = [json.loads(p["metadata"]) for p in db.inserted]
    assert all(m["seed"] == kc.REAL_TAG for m in metas)
    keys = {m["kb_key"] for m in metas}
    assert "horaires-samedi" not in keys
    # prix : catalogue en direct
    assert not any(k.startswith(("presta-", "tarifs-")) for k in keys)
    blob = " ".join(p["content"] for p in db.inserted)
    assert "Tanneurs" not in blob and "Léa" not in blob
    assert "le mardi de 9h à 19h" in blob
    assert db.commits == 1


@pytest.mark.asyncio
async def test_dry_run_n_ecrit_rien(tmp_path: Path, patched) -> None:
    db = _Db([], tmp_path)
    rep = await seed_mod.seed(db, "salon-reel", dry_run=True, backup_dir=tmp_path)
    assert rep["entries"] and not rep["demo"]
    assert db.log == [] and db.inserted == [] and db.commits == 0


@pytest.mark.asyncio
async def test_restore_remet_la_sauvegarde(tmp_path: Path, patched) -> None:
    kid = str(uuid4())
    rows = [_row("Ouvert le mardi.", "Horaires", kid=kid)]
    backup = {
        "business_id": str(BID),
        "slug": "salon-reel",
        "rows": [
            {
                **{k: v for k, v in r.items() if k != "metadata_"},
                "metadata": json.loads(r["metadata_"]),
            }
            for r in rows
        ],
    }
    for r in backup["rows"]:
        r["id"], r["created_at"] = str(r["id"]), r["created_at"].isoformat()
    path = tmp_path / "in" / "b.json"
    path.parent.mkdir()
    path.write_text(json.dumps(backup))
    db = _Db([_row("Autre chose.", "X")], tmp_path)
    rep = await seed_mod.restore(db, "salon-reel", path, backup_dir=tmp_path)
    assert rep["entries"] == 1 and rep["inserted"] == 1
    assert json.loads(db.inserted[0]["metadata"])["knowledge_id"] == kid
    assert db.inserted[0]["content"] == "Ouvert le mardi."
    # état d'avant exporté aussi
    assert Path(rep["backup"]).exists()


@pytest.mark.asyncio
async def test_restore_refuse_autre_salon(tmp_path: Path, patched) -> None:
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"business_id": str(uuid4()), "rows": []}))
    with pytest.raises(SystemExit, match="autre salon"):
        await seed_mod.restore(_Db([], tmp_path), "salon-reel", path, backup_dir=tmp_path)
