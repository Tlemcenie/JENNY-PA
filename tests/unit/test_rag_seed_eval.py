"""KB coiffeur seedée + jeu d'éval RAG + migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from jenny.eval import rag_eval as ev

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


seed = _load(ROOT / "scripts" / "seed_kb_coiffeur.py", "seed_kb_coiffeur")

_BUSINESS = {
    "name": "Salon démo",
    "email": "contact@demo.jenny.ai",
    "business_hours": {
        "mon": None,
        "tue": ["09:00", "19:00"],
        "wed": ["09:00", "19:00"],
        "thu": ["09:00", "21:00"],
        "fri": ["09:00", "19:00"],
        "sat": ["09:00", "18:00"],
        "sun": None,
    },
    "deposit_enabled": True,
    "deposit_percent": 25,
    "deposit_min_cents": 1000,
    "reminder_lead_minutes": 60,
    "day_reminder_lead_hours": 24,
    "loyalty_threshold": 10,
}
_PRESTAS = [
    {"name": "Coupe femme", "duration_minutes": 45, "price_cents": 3900},
    {"name": "Dégradé à la lame", "duration_minutes": 26, "price_cents": 1200},
    {"name": "Coupe homme", "duration_minutes": 30, "price_cents": 2500},
    {"name": "Brushing", "duration_minutes": 30, "price_cents": 2500},
    {"name": "Coloration", "duration_minutes": 90, "price_cents": 5500},
    {"name": "Balayage", "duration_minutes": 120, "price_cents": 8000},
    {"name": "Soin profond", "duration_minutes": 30, "price_cents": 2000},
    {"name": "Barbe", "duration_minutes": 20, "price_cents": 1500},
]


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return seed.build_entries(_BUSINESS, _PRESTAS, demo=True)


def _by_key(entries: list[dict]) -> dict[str, dict]:
    return {e["key"]: e for e in entries}


def test_taille_et_cles_uniques(entries: list[dict]) -> None:
    assert 60 <= len(entries) <= 100
    assert len({e["key"] for e in entries}) == len(entries)
    assert all(e["content"] and e["title"] for e in entries)


def test_coherent_avec_la_base(entries: list[dict]) -> None:
    kb = _by_key(entries)
    assert "39 €" in kb["presta-coupe-femme"]["content"]
    assert "1h30" in kb["presta-coloration"]["content"]
    assert "le jeudi de 9h à 21h" in kb["horaires-semaine"]["content"]
    assert "fermé le lundi et le dimanche" in kb["horaires-fermeture"]["content"]
    assert "25 %" in kb["acompte-montant"]["content"]
    assert "10 €" in kb["acompte-montant"]["content"]
    assert "10 rendez-vous" in kb["fidelite"]["content"]
    assert "27,30 €" in kb["tarif-enfant"]["content"]


def test_sujets_volontairement_absents(entries: list[dict]) -> None:
    blob = " ".join(e["content"].lower() + " " + e["title"].lower() for e in entries)
    for word in ("extension", "lissage", "kératine", "maquillage", "recrut", "apprenti"):
        assert word not in blob, word


def test_formats() -> None:
    assert seed.fmt_price(2730) == "27,30 €"
    assert seed.fmt_price(3900) == "39 €"
    assert seed.fmt_duration(90) == "1h30"
    assert seed.fmt_duration(120) == "2 h"
    assert seed.fmt_duration(45) == "45 min"
    assert seed.fmt_hour("09:00") == "9h"
    assert seed.fmt_hour("19:30") == "19h30"


def test_jeu_eval_composition() -> None:
    qs = ev.load_questions()
    assert len(qs) >= 120
    syn = sum(q.kind == "synonyme" for q in qs) / len(qs)
    hors = sum(not q.answerable for q in qs) / len(qs)
    assert 0.10 <= syn <= 0.20
    assert 0.10 <= hors <= 0.25
    assert any(q.holdout for q in qs)


def test_jeu_eval_cles_existent(entries: list[dict]) -> None:
    keys = {e["key"] for e in entries}
    for q in ev.load_questions():
        if q.answerable:
            assert q.keys, q.q
            assert set(q.keys) <= keys, q.q
        else:
            assert not q.keys


def test_metriques_recherche() -> None:
    m = ev.retrieval_metrics([1, 2, None, 4])
    assert m["recall@1"] == 0.25
    assert m["recall@3"] == 0.5
    assert m["recall@5"] == 0.75
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0.25) / 4)


def test_metriques_decision() -> None:
    m = ev.decision_metrics([(True, False), (True, True), (False, True), (False, False)])
    assert m["false_gap_rate"] == 0.5
    assert m["false_answer_rate"] == 0.5


def test_rang_par_cle_ou_mots() -> None:
    q = ev.Question(q="?", keys=["a"])
    docs = [
        {"content": "x", "metadata": {"kb_key": "b"}},
        {"content": "y", "metadata": {"kb_key": "a"}},
    ]
    assert ev.first_rank(docs, q) == 2
    q2 = ev.Question(q="?", keywords=["Végétale"])
    assert ev.first_rank([{"content": "coloration vegetale", "metadata": {}}], q2) == 1


def test_migration_ids_et_garde_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    mig = _load(ROOT / "migrations" / "versions" / "h1i2j3k4l5m6_rag_hnsw_fts.py", "mig_rag")
    assert mig.revision == "jen_raghnsw_h1i2"
    assert mig.down_revision == "jen_nooverlap_g1h2"

    executed: list[str] = []

    class _Op:
        def get_bind(self):
            return type("B", (), {"dialect": type("D", (), {"name": "sqlite"})()})()

        def execute(self, sql: str) -> None:
            executed.append(sql)

    monkeypatch.setattr(mig, "op", _Op())
    mig.upgrade()
    mig.downgrade()
    assert executed == []
