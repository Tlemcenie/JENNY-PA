"""Trace de suppression : jeu réel seulement."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag import kb_coiffeur as kc
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.rag.vector_store import TOMBSTONE_KEY

BID = str(uuid4())
BUSINESS = {
    "name": "Salon Réel",
    "email": "bonjour@salon-reel.fr",
    "phone": "",
    "business_hours": {"tue": ["10:00", "18:30"], "sat": ["09:00", "17:00"]},
    "deposit_enabled": True,
    "deposit_percent": 30,
    "deposit_min_cents": 1500,
    "reminder_lead_minutes": 60,
    "day_reminder_lead_hours": 24,
    "loyalty_threshold": 0,
}
STAFF = ["Nora", "Malik"]
FAMS = kc.real_families(include_prices=True)
DEMO_TEAM = "L'équipe compte quatre coiffeurs : Léa, Sophie, Karim et Inès."


class _Emb:
    max_tokens = 128
    dimension = 4

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class _Db:
    """Table en mémoire, SQL du store."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if "pg_advisory" in sql:
            return SimpleNamespace()
        if sql.startswith("INSERT") and "NOT EXISTS" in sql:
            if not any(r["metadata"].get(TOMBSTONE_KEY) == params["key"] for r in self.rows):
                meta = json.loads(params["metadata"])
                self.rows.append({"content": "", "metadata": meta, "chunk_index": 0})
            return SimpleNamespace(rowcount=1)
        if sql.startswith("INSERT"):
            self.rows.append(
                {
                    "content": params["content"],
                    "metadata": json.loads(params["metadata"]),
                    "chunk_index": params["chunk_index"],
                }
            )
            return SimpleNamespace(rowcount=1)
        if sql.startswith("DELETE"):
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
        if sql.startswith("SELECT metadata_->>'knowledge_id' AS knowledge_id"):
            return SimpleNamespace(fetchall=lambda: self._grouped())
        if sql.startswith(f"SELECT DISTINCT metadata_->>'{TOMBSTONE_KEY}'"):
            keys = [
                SimpleNamespace(key=r["metadata"][TOMBSTONE_KEY])
                for r in self.rows
                if r["metadata"].get(TOMBSTONE_KEY)
            ]
            return SimpleNamespace(fetchall=lambda: keys)
        raise AssertionError(sql)

    def _grouped(self) -> list[SimpleNamespace]:
        groups: dict[str, list[dict]] = {}
        for r in self.rows:
            kid = r["metadata"].get("knowledge_id")
            if kid:
                groups.setdefault(kid, []).append(r)
        out = []
        for kid, rows in groups.items():
            rows = sorted(rows, key=lambda r: r["chunk_index"])
            first = rows[0]["metadata"]
            out.append(
                SimpleNamespace(
                    knowledge_id=kid,
                    title=first.get("title"),
                    category=first.get("category"),
                    source=first.get("source"),
                    contents=[r["content"] for r in rows],
                    metas=[json.dumps(r["metadata"]) for r in rows],
                    idx=[r["chunk_index"] for r in rows],
                    chunks_count=len(rows),
                    created_at=None,
                )
            )
        return out

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _kb(db: _Db) -> KnowledgeBase:
    return KnowledgeBase(business_id=BID, session=db, embedder=_Emb())


def _real() -> list[dict]:
    return kc.build_entries(BUSINESS, [], demo=False, include_prices=False, staff=STAFF)


async def _by_key(kb: KnowledgeBase) -> dict:
    return {e.metadata.get("kb_key"): e for e in await kb.list_entries()}


@pytest.mark.asyncio
async def test_fiche_demo_supprimee_la_vraie_arrive() -> None:
    db = _Db()
    kb = _kb(db)
    # reste d'un vieux --force
    demo = await kb.add_text(
        DEMO_TEAM,
        title="L'équipe",
        category="equipe",
        metadata={"kb_key": "equipe", "seed": kc.SEED_TAG},
    )
    # le gérant retire le faux
    assert await kb.delete_entry(demo.id)
    assert await kb.tombstones() == set()
    stats = await kc.sync_real_entries(kb, _real(), families=FAMS)
    team = (await _by_key(kb))["equipe"]
    assert team.content == "L'équipe du salon : Nora et Malik."
    assert team.metadata["seed"] == kc.REAL_TAG
    assert stats["deleted_by_owner"] == 0


@pytest.mark.asyncio
async def test_fiche_reelle_supprimee_reste_supprimee() -> None:
    db = _Db()
    kb = _kb(db)
    await kc.sync_real_entries(kb, _real(), families=FAMS)
    team = (await _by_key(kb))["equipe"]
    assert await kb.delete_entry(team.id)
    assert await kb.tombstones() == {"equipe"}
    stats = await kc.sync_real_entries(kb, _real(), families=FAMS)
    assert "equipe" not in await _by_key(kb)
    assert stats["deleted_by_owner"] == 1


@pytest.mark.asyncio
async def test_copie_retouchee_supprimee_garde_la_trace() -> None:
    db = _Db()
    kb = _kb(db)
    await kc.sync_real_entries(kb, _real(), families=FAMS)
    rdv = (await _by_key(kb))["gerer-rdv"]
    await kb.update_text_entry(
        rdv.id, rdv.content + " Sauf le samedi.", title=rdv.title, category=rdv.category
    )
    assert await kb.delete_entry(rdv.id)
    assert await kb.tombstones() == {"gerer-rdv"}


@pytest.mark.asyncio
async def test_cle_sans_seed_pas_de_trace() -> None:
    db = _Db()
    kb = _kb(db)
    # import ou restauration ancienne
    loose = await kb.add_text("Rappel la veille.", title="Rappels", metadata={"kb_key": "rappels"})
    assert await kb.delete_entry(loose.id)
    assert await kb.tombstones() == set()
