"""ner servi : prestations vérifiées."""

import json
from pathlib import Path

import pytest

from jenny.core.config import get_settings
from jenny.engine import factory
from jenny.engine.ner_guard import (
    GuardedNERPredictor,
    clean_service,
    looks_like_service,
    negated,
)
from ml.models.intent_head.data import frozen_split
from ml.models.ner.predict import NERPredictor

NER_PATH = Path("checkpoints/ner/best_model.pt")
NER_DATA = Path("data/generated/ner.jsonl")


class FakeTags(GuardedNERPredictor):
    """tags imposés, sans modèle."""

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self.pairs = pairs

    def predict_with_tags(self, text: str) -> list[tuple[str, str]]:
        return self.pairs


def _tags(text: str, tags: str) -> list[tuple[str, str]]:
    return list(zip(text.split(), tags.split(), strict=True))


class TestFiltre:
    """mots de prestation."""

    @pytest.mark.parametrize(
        "span",
        ["coupe", "colo + mèches", "balyage", "lissage brésilien", "Dégradé à la lame", "soin"],
    )
    def test_accepte(self, span: str) -> None:
        assert looks_like_service(span)

    @pytest.mark.parametrize(
        "span", ["ouverts", "vraie", "8", "tatouage", "rdv", "pneus", "très", "nombre"]
    )
    def test_refuse(self, span: str) -> None:
        assert not looks_like_service(span)

    @pytest.mark.parametrize(
        ("span", "attendu"),
        [
            ("coupe femme mardi", "coupe femme"),
            ("brushing samedi", "brushing"),
            ("coupe femme.", "coupe femme"),
            ("coupe 14h", "coupe"),
            ("coupe sans", "coupe"),
            ("samedi", ""),
        ],
    )
    def test_nettoie(self, span: str, attendu: str) -> None:
        assert clean_service(span) == attendu

    def test_negation(self) -> None:
        phrase = "Je veux une coupe mais PAS de coloration"
        toks = phrase.split()
        assert negated(toks, toks.index("coloration"))
        assert not negated(toks, toks.index("coupe"))
        phrase = "Je ne veux pas attendre, une coupe"
        toks = phrase.split()
        assert not negated(toks, toks.index("coupe"))

    def test_gold_du_ner_accepte(self) -> None:
        spans = []
        for line in NER_DATA.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            spans += [e["value"] for e in row["entities"] if e["type"] == "SERVICE"]
        ok = sum(looks_like_service(clean_service(s) or s) for s in spans)
        # mesuré : 1230 / 1231
        assert ok / len(spans) >= 0.99


class TestDecodage:
    """mêmes entités, prestations jointes."""

    def test_deux_prestations(self) -> None:
        text = "une coupe femme et une coloration vendredi"
        ner = FakeTags(_tags(text, "O B-SERVICE I-SERVICE O O B-SERVICE B-DATE"))
        assert ner.predict(text) == {"service": "coupe femme et coloration", "date": "vendredi"}

    def test_faux_service_retire(self) -> None:
        text = "Vous êtes ouverts samedi ?"
        ner = FakeTags(_tags(text, "O O B-SERVICE B-DATE O"))
        assert ner.predict(text) == {"date": "samedi"}

    def test_service_refuse(self) -> None:
        text = "une coupe mais pas de coloration"
        ner = FakeTags(_tags(text, "O B-SERVICE O O O B-SERVICE"))
        assert ner.predict(text) == {"service": "coupe"}

    def test_i_orphelin_ignore(self) -> None:
        text = "rdv demain 14h"
        ner = FakeTags(_tags(text, "O I-DATE B-TIME"))
        assert ner.predict(text) == {"time": "14h"}

    def test_doublon_une_fois(self) -> None:
        text = "coupe et Coupe"
        ner = FakeTags(_tags(text, "B-SERVICE O B-SERVICE"))
        assert ner.predict(text) == {"service": "coupe"}


@pytest.mark.skipif(not NER_PATH.exists(), reason="checkpoint ner absent")
class TestVraiModele:
    """vrai bigru, chargé une fois."""

    @pytest.fixture(scope="class")
    def pair(self) -> tuple[GuardedNERPredictor, NERPredictor]:
        g = GuardedNERPredictor.from_checkpoint(NER_PATH)
        # cpu : plus rapide ici
        g.model.to("cpu")
        g.config.device = "cpu"
        return g, NERPredictor(g.model, g.vocab, g.config)

    def test_autres_entites_identiques(self, pair) -> None:
        g, brut = pair
        rows = [json.loads(x) for x in NER_DATA.read_text(encoding="utf-8").splitlines()]
        for i in frozen_split(len(rows))["test"][:300]:
            text = rows[i]["text"]
            a = {k: v for k, v in g.predict(text).items() if k != "service"}
            b = {k: v for k, v in brut.predict(text).items() if k != "service"}
            assert a == b, text

    def test_cas_mesures(self, pair) -> None:
        g, _ = pair
        assert "service" not in g.predict("Vous êtes ouverts samedi ?")
        assert "service" not in g.predict("Ma fille de 8 ans peut venir avec moi ?")
        got = g.predict("je veux une coupe femme ET une coloration vendredi 9h30")
        assert got["service"] == "coupe femme et coloration"

    def test_fabrique_sert_le_filtre(self, monkeypatch) -> None:
        monkeypatch.setenv("JENNY_NER_MODEL_PATH", str(NER_PATH))
        get_settings.cache_clear()
        try:
            ner = factory.load_ner_predictor()
        finally:
            get_settings.cache_clear()
        assert isinstance(ner, GuardedNERPredictor)
        assert isinstance(ner, NERPredictor)
