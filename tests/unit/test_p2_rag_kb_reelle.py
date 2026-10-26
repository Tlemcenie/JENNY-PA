"""Fiches d'un vrai salon : rien d'inventé."""

from __future__ import annotations

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jenny.rag import kb_coiffeur as kc

HOURS = {
    "mon": None,
    "tue": ["10:00", "18:30"],
    "wed": ["10:00", "18:30"],
    "thu": ["10:00", "20:00"],
    "fri": ["10:00", "18:30"],
    "sat": ["09:00", "17:00"],
    "sun": None,
}
BUSINESS = {
    "name": "Salon Réel",
    "email": "bonjour@salon-reel.fr",
    "phone": "01 02 03 04 05",
    "business_hours": HOURS,
    "deposit_enabled": True,
    "deposit_percent": 30,
    "deposit_min_cents": 1500,
    "reminder_lead_minutes": 120,
    "day_reminder_lead_hours": 24,
    "loyalty_threshold": 8,
}
PRESTAS = [
    {"name": "Coupe femme", "duration_minutes": 50, "price_cents": 4200, "description": ""},
    {"name": "Coloration", "duration_minutes": 95, "price_cents": 6150, "description": None},
    {"name": "Barbe", "duration_minutes": 20, "price_cents": 1500, "is_active": False},
]
# faits inventés de la démo
_DEMO_ONLY = (
    "Tanneurs",
    "Voltaire",
    "Olaplex",
    "Kérastase",
    "220 €",
    "Wi-Fi",
    "jours fériés",
    "Inès",
    "7 jours",
    "chèques",
    "Île-de-France",
    "moins de 12 ans",
)


def _real(**kw) -> list[dict]:
    return kc.build_entries(BUSINESS, PRESTAS, demo=False, **kw)


def test_demo_explicite_obligatoire() -> None:
    with pytest.raises(TypeError):
        kc.build_entries(BUSINESS, PRESTAS)  # type: ignore[call-arg]


def test_reel_sans_fait_invente() -> None:
    blob = " ".join(e["content"] + " " + e["title"] for e in _real(staff=["Nora"]))
    for word in _DEMO_ONLY:
        assert word not in blob, word


def test_reel_montants_tous_tires_de_la_base() -> None:
    allowed = {kc.fmt_price(p["price_cents"]) for p in PRESTAS if p.get("is_active", True)}
    allowed.add(kc.fmt_price(BUSINESS["deposit_min_cents"]))
    for e in _real():
        for amount in re.findall(r"\d+(?:,\d+)? €", e["content"]):
            assert amount in allowed, (e["key"], amount)


def test_reel_horaires_depuis_business_hours() -> None:
    by = {e["key"]: e for e in _real()}
    week = by["horaires-semaine"]["content"]
    assert "le jeudi de 10h à 20h" in week
    assert "10h à 18h30" in week
    assert "fermé le lundi et le dimanche" in week
    assert by["horaires-samedi"]["content"].endswith("de 9h à 17h.")
    assert by["horaires-nocturne"]["content"] == "Le jeudi, le salon reste ouvert jusqu'à 20h."
    # rien sur les fériés
    assert by["horaires-fermeture"]["content"] == "Le salon est fermé le lundi et le dimanche."


@pytest.mark.parametrize(
    "hours",
    [None, {}, {"mon": None, "tue": None}, {"tue": "09:00-19:00"}, {"tue": ["9h", "19h"]}],
)
def test_pas_d_horaires_pas_de_fiche(hours) -> None:
    entries = kc.build_entries({**BUSINESS, "business_hours": hours}, PRESTAS, demo=False)
    assert not [e for e in entries if e["key"].startswith("horaires-")]


def test_reel_depot_rappels_fidelite_equipe() -> None:
    by = {e["key"]: e for e in _real(staff=["Nora", " ", "Sami"])}
    assert "30 %" in by["acompte-montant"]["content"]
    assert "minimum 15 €" in by["acompte-montant"]["content"]
    assert "2 h avant" not in by["rappels"]["content"]
    assert "120 minutes avant" in by["rappels"]["content"]
    assert "8 rendez-vous" in by["fidelite"]["content"]
    assert by["equipe"]["content"] == "L'équipe du salon : Nora et Sami."
    assert "01 02 03 04 05" in by["contact"]["content"]
    assert "virtuelle" in by["assistante"]["content"]


def test_reel_sans_equipe_ni_prix() -> None:
    keys = {e["key"] for e in _real(include_prices=False)}
    assert "equipe" not in keys and "choisir-coiffeur" not in keys
    assert not any(k.startswith(("presta-", "tarifs-")) for k in keys)


def test_reel_cles_dans_les_familles() -> None:
    fams = kc.real_families(include_prices=True)
    for e in _real(staff=["Nora"]):
        assert kc._managed(e["key"], fams), e["key"]
    assert len({e["key"] for e in _real()}) == len(_real())


def test_inactive_absente() -> None:
    keys = {e["key"] for e in _real()}
    assert "presta-barbe" not in keys
    assert "presta-coupe-femme" in keys


# ── synchro des fiches ──


class _KB:
    """KB en mémoire."""

    def __init__(self, entries=None) -> None:
        self.entries: dict[str, SimpleNamespace] = {}
        for e in entries or []:
            self._put(**e)
        self.calls: list[str] = []

    def _put(self, *, title, content, category="general", metadata=None, id=None):
        eid = id or str(uuid4())
        self.entries[eid] = SimpleNamespace(
            id=eid, title=title, content=content, category=category, metadata=metadata or {}
        )
        return eid

    async def list_entries(self):
        return list(self.entries.values())

    async def add_text(self, content, title="", category="general", metadata=None):
        self.calls.append("add")
        self._put(title=title, content=content, category=category, metadata=metadata)

    async def update_text_entry(
        self, knowledge_id, content, title="", category="general", metadata=None
    ):
        self.calls.append("update")
        old = self.entries[knowledge_id]
        self._put(
            id=knowledge_id,
            title=title,
            content=content,
            category=category,
            metadata={**old.metadata, **(metadata or {})},
        )

    async def delete_entry(self, knowledge_id, tombstone=True):
        self.calls.append("delete")
        return self.entries.pop(knowledge_id, None) is not None

    def by_key(self) -> dict[str, SimpleNamespace]:
        return {
            e.metadata.get("kb_key"): e for e in self.entries.values() if e.metadata.get("kb_key")
        }


FAMS = kc.real_families(include_prices=False)


@pytest.mark.asyncio
async def test_sync_ajoute_puis_idempotent() -> None:
    kb = _KB()
    entries = _real(include_prices=False)
    first = await kc.sync_real_entries(kb, entries, families=FAMS)
    assert first["added"] == len(entries)
    kb.calls.clear()
    again = await kc.sync_real_entries(kb, entries, families=FAMS)
    assert again == {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "kept_owner": 0,
        "deleted_by_owner": 0,
    }
    assert kb.calls == []


@pytest.mark.asyncio
async def test_sync_horaires_changes_mises_a_jour() -> None:
    kb = _KB()
    await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    before_id = kb.by_key()["horaires-semaine"].id
    late = {**HOURS, "thu": ["10:00", "18:30"]}
    newer = kc.build_entries(
        {**BUSINESS, "business_hours": late}, PRESTAS, demo=False, include_prices=False
    )
    stats = await kc.sync_real_entries(kb, newer, families=FAMS)
    by = kb.by_key()
    assert by["horaires-semaine"].id == before_id
    assert "jeudi" in by["horaires-semaine"].content and "20h" not in by["horaires-semaine"].content
    # plus de nocturne
    assert "horaires-nocturne" not in by
    assert stats["updated"] >= 1 and stats["removed"] == 1


@pytest.mark.asyncio
async def test_sync_fiche_du_gerant_gardee() -> None:
    owner = {"title": "Horaires d'ouverture", "content": "Ouvert tous les jours sauf lundi."}
    kb = _KB([owner])
    stats = await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    assert stats["kept_owner"] == 1
    texts = [e.content for e in kb.entries.values() if e.title == "Horaires d'ouverture"]
    assert texts == ["Ouvert tous les jours sauf lundi."]


@pytest.mark.asyncio
async def test_sync_vieille_fiche_codee_en_dur_remplacee() -> None:
    legacy = {"title": "Horaires d'ouverture", "content": kc.LEGACY_HOURS_TEXT}
    kb = _KB([legacy, dict(legacy)])
    stats = await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    hours = [e for e in kb.entries.values() if e.title == "Horaires d'ouverture"]
    assert len(hours) == 1
    assert "mardi au samedi" not in hours[0].content
    assert hours[0].metadata["seed"] == kc.REAL_TAG
    assert stats["removed"] == 1 and stats["updated"] == 1


@pytest.mark.asyncio
async def test_sync_sans_horaires_retire_l_invente() -> None:
    kb = _KB([{"title": "Horaires d'ouverture", "content": kc.LEGACY_HOURS_TEXT}])
    entries = kc.build_entries(
        {**BUSINESS, "business_hours": None}, PRESTAS, demo=False, include_prices=False
    )
    await kc.sync_real_entries(kb, entries, families=FAMS)
    assert not [e for e in kb.entries.values() if e.content == kc.LEGACY_HOURS_TEXT]


@pytest.mark.asyncio
async def test_sync_route_ne_touche_pas_aux_prix() -> None:
    kb = _KB()
    await kc.sync_real_entries(kb, _real(include_prices=True), families=kc.real_families(True))
    assert "presta-coupe-femme" in kb.by_key()
    # la route (sans prix) passe
    await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    assert "presta-coupe-femme" in kb.by_key()


@pytest.mark.asyncio
async def test_sync_ignore_fiches_demo() -> None:
    demo = kc.build_entries(BUSINESS, PRESTAS, demo=True)
    kb = _KB(
        [
            {
                "title": e["title"],
                "content": e["content"],
                "category": e["category"],
                "metadata": {"kb_key": e["key"], "seed": kc.SEED_TAG},
            }
            for e in demo
        ]
    )
    stats = await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    # fiches démo jamais effacées
    assert stats["removed"] == 0
    assert len([e for e in kb.entries.values() if e.metadata.get("seed") == kc.SEED_TAG]) == len(
        demo
    )


# ── horaires modifiés plus tard ──


def _session(dialect: str) -> SimpleNamespace:
    return SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)))


def _salon_with(hours):
    async def load(_s, _bid):
        return {**BUSINESS, "business_hours": hours}, PRESTAS, []

    return load


@pytest.mark.asyncio
async def test_refresh_hours_suit_le_changement(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _KB()
    await kc.sync_real_entries(kb, _real(include_prices=False), families=FAMS)
    monkeypatch.setattr(kc, "load_salon", _salon_with({**HOURS, "thu": ["10:00", "18:30"]}))
    stats = await kc.refresh_hours(_session("postgresql"), uuid4(), kb=kb)
    by = kb.by_key()
    assert stats is not None and stats["updated"] >= 1
    assert "20h" not in by["horaires-semaine"].content
    assert "horaires-nocturne" not in by
    # le reste ne bouge pas
    assert "acompte-montant" in by and "assistante" in by


@pytest.mark.asyncio
async def test_refresh_hours_salon_jamais_seede(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _KB([{"title": "Ma fiche", "content": "Texte du gérant."}])
    monkeypatch.setattr(kc, "load_salon", _salon_with(HOURS))
    assert await kc.refresh_hours(_session("postgresql"), uuid4(), kb=kb) is None
    assert kb.calls == []


@pytest.mark.asyncio
async def test_refresh_hours_sqlite_rien() -> None:
    assert await kc.refresh_hours(_session("sqlite"), uuid4(), kb=_KB()) is None
