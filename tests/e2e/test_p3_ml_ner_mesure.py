"""ner coupé : la mesure le prouve."""

import importlib.util
from pathlib import Path

import pytest

from jenny.core.config import Settings

SCRIPT = Path("scripts/eval_ner_slots.py")
CKPTS = (Path("checkpoints/intent_head/head.npz"), Path("checkpoints/ner/best_model.pt"))


def _load():
    """charge le script d'éval."""
    spec = importlib.util.spec_from_file_location("eval_ner_slots", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ev():
    return _load()


class TestGold:
    """gold à jour des parcours."""

    def test_tous_les_messages_annotes(self, ev) -> None:
        msgs = {m for conv in ev.scenario_messages() for m in conv}
        gold = ev.load_gold()
        assert len(msgs) > 40
        assert msgs <= set(gold), sorted(msgs - set(gold))

    def test_juge(self, ev) -> None:
        g = {"service": ["coupe"], "date": None, "time": "14:00"}
        assert ev.judge("service", "Coupe femme", g, set()) == "juste"
        assert ev.judge("service", "ouverts", g, set()) == "faux"
        assert ev.judge("time", "14:00", g, set()) == "juste"
        assert ev.judge("date", "2026-01-01", g, set()) == "faux"
        assert ev.judge("date", None, g, set()) is None

    def test_ecart_casse_ignore(self, ev) -> None:
        assert ev.gap_kind("coupe femme", "Coupe femme") is None
        assert ev.gap_kind("coupe femme mardi", "Coupe femme") == "meme_presta"
        assert ev.gap_kind("coupe", None) == "servi_seul"


def test_ner_coupe_par_defaut() -> None:
    # écrase la presta du rdv
    assert Settings(_env_file=None).enable_ner_model is False


@pytest.mark.skipif(not all(p.exists() for p in CKPTS), reason="checkpoints absents")
@pytest.mark.asyncio
async def test_ner_remplit_plus_mais_risque(ev) -> None:
    engines = ev.build_engines()
    convs = [(m, ev.CATALOG) for m in ev.scenario_messages()]
    gold = ev.load_gold()
    res, risk = {}, {}
    for name, eng in engines.items():
        runs = await ev.replay(eng, convs)
        res[name] = ev.score(runs, gold, ev.RDV_INTENTS)
        risk[name] = ev.risks(runs, [c for _, c in convs])
    avec, sans = res["avec_ner"], res["sans_ner"]
    # mesuré : 88,9 contre 55,6
    assert avec["service"]["rappel_pct"] > sans["service"]["rappel_pct"]
    assert avec["service"]["precision_pct"] >= 90.0
    # mesuré : 83,3 contre 66,7
    assert avec["date"]["rappel_pct"] > sans["date"]["rappel_pct"]
    assert avec["time"]["rappel_pct"] >= sans["time"]["rappel_pct"]
    # mais : presta écrasée, hors catalogue
    assert risk["avec_ner"]["ecrase_hors_rdv"]["service"] > 0
    assert risk["avec_ner"]["hors_catalogue"] > 0
    # sans ner : aucun risque
    assert risk["sans_ner"]["pose_hors_rdv"] == 0
    assert risk["sans_ner"]["hors_catalogue"] == 0
    assert set(risk["sans_ner"]["ecrase_hors_rdv"].values()) == {0}


class TestRisques:
    """compteurs de risques."""

    def test_ecrase_pendant_question(self, ev) -> None:
        conv = [
            {
                "intent": "appointment",
                "slots": {"service": "Coupe homme"},
                "state": {"service": "Coupe homme"},
            },
            {
                "intent": "pricing",
                "slots": {"service": "coupe femme"},
                "state": {"service": "coupe femme"},
            },
            {
                "intent": "appointment",
                "slots": {"time": "14:00"},
                "state": {"service": "coupe femme", "time": "14:00"},
            },
        ]
        r = ev.risks([conv], [ev.CATALOG])
        assert r["ecrase_hors_rdv"] == {"service": 1, "date": 0, "time": 0}
        assert r["pose_hors_rdv"] == 1
        assert r["hors_catalogue"] == 0

    def test_hors_catalogue(self, ev) -> None:
        conv = [{"intent": "appointment", "slots": {"service": "lissage brésilien"}, "state": {}}]
        r = ev.risks([conv], [ev.CATALOG])
        assert r["hors_catalogue"] == 1
        assert r["exemples_hors_catalogue"] == ["lissage brésilien"]
