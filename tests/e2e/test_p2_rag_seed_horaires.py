"""Seed : fiche horaires = vrais horaires."""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from jenny.api.routes import prestations as route
from jenny.db.session import async_session_factory
from jenny.domain.models import Business
from jenny.domain.models.prestation import Prestation
from jenny.rag import kb_coiffeur as kc
from jenny.scripts import seed_demo

HOURS = {"mon": ["08:30", "18:00"], "wed": ["08:30", "18:00"], "sat": ["09:00", "16:00"]}


class _PgDb:
    """Session « postgres » factice."""

    def __init__(self) -> None:
        self.rollbacks = 0
        self.dialect = SimpleNamespace(name="postgresql")

    def get_bind(self):
        return self

    async def rollback(self) -> None:
        self.rollbacks += 1


class _KB:
    instances: ClassVar[list[_KB]] = []

    def __init__(self, business_id, session) -> None:
        self.added: list[dict] = []
        _KB.instances.append(self)

    async def list_entries(self):
        return []

    async def add_text(self, content, title="", category="general", metadata=None):
        self.added.append({"title": title, "content": content, "metadata": metadata})


def _salon(hours):
    async def load(_db, _bid):
        biz = {
            "id": uuid4(),
            "name": "Salon",
            "business_hours": hours,
            "deposit_enabled": False,
            "loyalty_threshold": 0,
        }
        return biz, [{"name": "Coupe femme", "duration_minutes": 45, "price_cents": 3900}], []

    return load


@pytest.mark.asyncio
async def test_route_fiche_horaires_depuis_business_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _KB.instances.clear()
    monkeypatch.setattr(route, "KnowledgeBase", _KB)
    monkeypatch.setattr(route, "load_salon", _salon(HOURS))
    n = await route._seed_knowledge(_PgDb(), uuid4())
    added = _KB.instances[0].added
    assert n == len(added) > 0
    hours = next(a for a in added if a["title"] == "Horaires d'ouverture")
    assert "le lundi et mercredi de 8h30 à 18h" in hours["content"]
    assert "mardi au samedi" not in hours["content"]
    assert hours["metadata"] == {"kb_key": "horaires-semaine", "seed": kc.REAL_TAG}
    # prix : catalogue en direct
    assert not any(a["metadata"]["kb_key"].startswith("presta-") for a in added)


@pytest.mark.asyncio
async def test_route_sans_horaires_pas_de_fiche(monkeypatch: pytest.MonkeyPatch) -> None:
    _KB.instances.clear()
    monkeypatch.setattr(route, "KnowledgeBase", _KB)
    monkeypatch.setattr(route, "load_salon", _salon(None))
    await route._seed_knowledge(_PgDb(), uuid4())
    titles = {a["title"] for a in _KB.instances[0].added}
    assert "Horaires d'ouverture" not in titles
    assert "Qui répond dans ce chat" in titles


@pytest.mark.asyncio
async def test_route_erreur_kb_ignoree(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(_db, _bid):
        raise RuntimeError("pgvector indisponible")

    monkeypatch.setattr(route, "load_salon", boom)
    db = _PgDb()
    assert await route._seed_knowledge(db, uuid4()) == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_seed_demo_salon_coherent(db_tables: None) -> None:
    bid = await seed_demo._seed()
    assert bid is not None
    async with async_session_factory() as s:
        biz = await s.get(Business, bid)
        assert biz.business_hours == seed_demo.DEMO_HOURS
        n = (
            await s.execute(select(func.count(Prestation.id)).where(Prestation.business_id == bid))
        ).scalar_one()
        assert n == len(kc.DEFAULT_COIFFEUR) + 1
        business, prestas, _staff = await kc.load_salon(s, bid)
    entries = {e["key"]: e for e in kc.build_entries(business, prestas, demo=True)}
    assert "le jeudi de 9h à 21h" in entries["horaires-semaine"]["content"]
    assert "25 %" in entries["acompte-montant"]["content"]
    assert "presta-degrade-a-la-lame" in entries
    # sans pgvector : sauté sans planter
    await seed_demo._seed_knowledge(bid)
