"""Synchro des fiches réelles : retouches, suppressions, doublons."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.api.routes import prestations as route
from jenny.rag import kb_coiffeur as kc

HOURS = {
    "tue": ["10:00", "18:30"],
    "wed": ["10:00", "18:30"],
    "thu": ["10:00", "20:00"],
    "sat": ["09:00", "17:00"],
}
BUSINESS = {
    "name": "Salon Réel",
    "email": "bonjour@salon-reel.fr",
    "phone": "",
    "business_hours": HOURS,
    "deposit_enabled": True,
    "deposit_percent": 30,
    "deposit_min_cents": 1500,
    "reminder_lead_minutes": 60,
    "day_reminder_lead_hours": 24,
    "loyalty_threshold": 0,
}
PRESTAS = [{"name": "Coupe femme", "duration_minutes": 45, "price_cents": 3900}]
FAMS = kc.real_families(include_prices=True)


def _real(business=None, **kw) -> list[dict]:
    return kc.build_entries(business or BUSINESS, PRESTAS, demo=False, include_prices=False, **kw)


class _KB:
    """KB en mémoire, comme la vraie."""

    def __init__(self) -> None:
        self.entries: dict[str, SimpleNamespace] = {}
        self.tombs: set[str] = set()
        self.calls: list[str] = []
        self.in_batch = 0

    def put(self, *, title, content, category="general", metadata=None, id=None) -> str:
        eid = id or str(uuid4())
        self.entries[eid] = SimpleNamespace(
            id=eid, title=title, content=content, category=category, metadata=metadata or {}
        )
        return eid

    @asynccontextmanager
    async def batch(self):
        self.calls.append("batch")
        self.in_batch += 1
        try:
            yield self
        finally:
            self.in_batch -= 1

    def _write(self, name: str) -> None:
        # écrit sous le verrou
        assert self.in_batch, name
        self.calls.append(name)

    async def list_entries(self):
        return list(self.entries.values())

    async def tombstones(self):
        return set(self.tombs)

    async def add_text(self, content, title="", category="general", metadata=None):
        self._write("add")
        self.put(title=title, content=content, category=category, metadata=metadata)

    async def update_text_entry(
        self, knowledge_id, content, title="", category="general", metadata=None
    ):
        if self.in_batch:
            self._write("update")
        old = self.entries[knowledge_id]
        # la route n'envoie pas de meta
        self.put(
            id=knowledge_id,
            title=title,
            content=content,
            category=category,
            metadata={**old.metadata, **(metadata or {})},
        )

    async def delete_entry(self, knowledge_id, tombstone=True):
        if self.in_batch:
            self._write("delete")
        old = self.entries.pop(knowledge_id, None)
        if old is not None and tombstone and old.metadata.get("kb_key"):
            self.tombs.add(old.metadata["kb_key"])
        return old is not None

    def by_key(self) -> dict[str, SimpleNamespace]:
        return {e.metadata["kb_key"]: e for e in self.entries.values() if e.metadata.get("kb_key")}


async def _seeded() -> _KB:
    kb = _KB()
    await kc.sync_real_entries(kb, _real(), families=FAMS)
    return kb


@pytest.mark.asyncio
async def test_fiche_retouchee_jamais_ecrasee() -> None:
    kb = await _seeded()
    rdv = kb.by_key()["gerer-rdv"]
    edit = rdv.content + " Merci de prévenir 24 h avant."
    # le gérant édite (route KB)
    await kb.update_text_entry(rdv.id, edit, title=rdv.title, category=rdv.category)
    assert kc.is_edited(kb.entries[rdv.id])
    stats = await kc.sync_real_entries(kb, _real(), families=FAMS)
    assert kb.entries[rdv.id].content == edit
    assert stats["updated"] == 0 and stats["kept_owner"] == 1 and stats["added"] == 0


@pytest.mark.asyncio
async def test_fiche_retouchee_gardee_meme_si_le_fait_disparait() -> None:
    kb = await _seeded()
    night = kb.by_key()["horaires-nocturne"]
    await kb.update_text_entry(
        night.id, "Nocturne le jeudi, sauf en août.", title=night.title, category="horaires"
    )
    later = _real({**BUSINESS, "business_hours": {**HOURS, "thu": ["10:00", "18:30"]}})
    await kc.sync_real_entries(kb, later, families=FAMS)
    assert kb.entries[night.id].content == "Nocturne le jeudi, sauf en août."


@pytest.mark.asyncio
async def test_retour_au_texte_genere_redevient_a_nous() -> None:
    kb = await _seeded()
    acompte = kb.by_key()["acompte-montant"]
    original = acompte.content
    await kb.update_text_entry(
        acompte.id, "Autre texte.", title=acompte.title, category="politique"
    )
    await kb.update_text_entry(acompte.id, original, title=acompte.title, category="politique")
    off = _real({**BUSINESS, "deposit_enabled": False})
    stats = await kc.sync_real_entries(kb, off, families=FAMS)
    assert stats["updated"] == 1
    assert "Aucun acompte" in kb.entries[acompte.id].content


@pytest.mark.asyncio
async def test_fiche_supprimee_par_le_gerant_pas_recreee() -> None:
    kb = await _seeded()
    await kb.delete_entry(kb.by_key()["liste-attente"].id)
    stats = await kc.sync_real_entries(kb, _real(), families=FAMS)
    assert "liste-attente" not in kb.by_key()
    assert stats["added"] == 0 and stats["deleted_by_owner"] == 1


@pytest.mark.asyncio
async def test_fait_retire_par_la_synchro_peut_revenir() -> None:
    kb = await _seeded()
    early = _real({**BUSINESS, "business_hours": {**HOURS, "thu": ["10:00", "18:30"]}})
    await kc.sync_real_entries(kb, early, families=FAMS)
    assert "horaires-nocturne" not in kb.by_key()
    # pas une suppression du gérant
    assert kb.tombs == set()
    await kc.sync_real_entries(kb, _real(), families=FAMS)
    assert "horaires-nocturne" in kb.by_key()


@pytest.mark.asyncio
async def test_doublons_d_un_seed_parallele_nettoyes() -> None:
    kb = await _seeded()
    for e in _real():
        # 2e seed concurrent d'avant
        kb.put(
            title=e["title"],
            content=e["content"],
            category=e["category"],
            metadata={"kb_key": e["key"], "seed": kc.REAL_TAG},
        )
    stats = await kc.sync_real_entries(kb, _real(), families=FAMS)
    keys = [e.metadata["kb_key"] for e in kb.entries.values()]
    assert len(keys) == len(set(keys)) == len(_real())
    assert stats["removed"] == len(_real())
    assert kb.tombs == set()


@pytest.mark.asyncio
async def test_toutes_les_ecritures_sous_le_verrou() -> None:
    kb = await _seeded()
    assert kb.calls[0] == "batch" and "add" in kb.calls
    kb.calls.clear()
    await kc.sync_real_entries(kb, _real({**BUSINESS, "deposit_enabled": False}), families=FAMS)
    assert kb.calls == ["batch", "update"]


@pytest.mark.asyncio
async def test_anciennes_fiches_prix_retirees() -> None:
    kb = _KB()
    with_prices = kc.build_entries(BUSINESS, PRESTAS, demo=False, include_prices=True)
    await kc.sync_real_entries(kb, with_prices, families=FAMS)
    assert "presta-coupe-femme" in kb.by_key()
    await kc.sync_real_entries(kb, _real(), families=FAMS)
    keys = set(kb.by_key())
    assert not any(k.startswith(("presta-", "tarifs-")) for k in keys)


# ── suivi après changement ──


def _pg() -> SimpleNamespace:
    return SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )


def _salon(business, staff=()):
    async def load(_s, _bid):
        return dict(business), list(PRESTAS), list(staff)

    return load


@pytest.mark.asyncio
async def test_refresh_suit_acompte_rappels_equipe(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = await _seeded()
    later = {**BUSINESS, "deposit_enabled": False, "day_reminder_lead_hours": 0}
    monkeypatch.setattr(kc, "load_salon", _salon(later, staff=["Nora"]))
    stats = await kc.refresh_real_entries(_pg(), uuid4(), kb=kb)
    by = kb.by_key()
    assert stats is not None
    assert "Aucun acompte" in by["acompte-montant"].content
    assert "la veille" not in by["rappels"].content
    assert by["equipe"].content == "L'équipe du salon : Nora."


@pytest.mark.asyncio
async def test_refresh_salon_jamais_seede(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _KB()
    kb.put(title="Ma fiche", content="Texte du gérant.")
    monkeypatch.setattr(kc, "load_salon", _salon(BUSINESS))
    assert await kc.refresh_real_entries(_pg(), uuid4(), kb=kb) is None
    assert kb.calls == []


@pytest.mark.asyncio
async def test_refresh_sqlite_rien() -> None:
    sqlite = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    )
    assert await kc.refresh_real_entries(sqlite, uuid4(), kb=_KB()) is None


@pytest.mark.asyncio
async def test_route_retire_les_fiches_prix_du_script(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _KB()
    old = kc.build_entries(BUSINESS, PRESTAS, demo=False, include_prices=True)
    await kc.sync_real_entries(kb, old, families=FAMS)
    monkeypatch.setattr(route, "KnowledgeBase", lambda business_id, session: kb)
    monkeypatch.setattr(route, "load_salon", _salon(BUSINESS))

    class _Db:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def rollback(self) -> None:
            raise AssertionError("pas d'erreur attendue")

    await route._seed_knowledge(_Db(), uuid4())
    assert not any(k.startswith(("presta-", "tarifs-")) for k in kb.by_key())


class _LockDb:
    def __init__(self, dialect: str) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.sql: list[tuple[str, dict]] = []

    def get_bind(self):
        return self

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params or {}))
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_seed_un_a_la_fois_par_salon() -> None:
    bid = uuid4()
    pg = _LockDb("postgresql")
    assert await route._lock_seed(pg, bid)
    sql, params = pg.sql[0]
    assert "pg_advisory_xact_lock" in sql
    assert params["key"] == f"jenny:seed-coiffeur:{bid}"
    lite = _LockDb("sqlite")
    assert not await route._lock_seed(lite, bid)
    assert lite.sql == []
