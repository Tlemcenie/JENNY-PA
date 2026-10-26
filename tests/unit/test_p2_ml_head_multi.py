"""tête : npz sans pickle, multi-intention."""

from pathlib import Path

import numpy as np
import pytest

from ml.models.intent_head import predict as head_predict
from ml.models.intent_head import train as head_train
from ml.models.intent_head.data import Group, frozen_split, labels_of, load_rows
from ml.models.intent_head.predict import (
    DEFAULT_PATH,
    EmbeddingIntentPredictor,
    load_checkpoint,
    save_checkpoint,
)

# planchers mesurés sur le test
RAPPEL_MULTI_MIN = 85.0
FAUX_MULTI_MAX = 2.0
PROBE = Path("data/generated/intents_multi_probe.jsonl")


@pytest.fixture(scope="module")
def head() -> EmbeddingIntentPredictor:
    if not DEFAULT_PATH.exists():
        pytest.skip("checkpoint tête absent")
    try:
        return EmbeddingIntentPredictor.from_checkpoint(DEFAULT_PATH)
    except OSError as e:
        pytest.skip(f"encodeur indisponible : {e}")


@pytest.fixture(scope="module")
def test_rows() -> list[dict]:
    rows = load_rows()
    return [rows[i] for i in frozen_split(len(rows))["test"]]


class TestFormat:
    """aucun pickle au chargement."""

    def test_pas_de_joblib(self) -> None:
        assert "joblib" not in vars(head_predict)
        assert DEFAULT_PATH.suffix == ".npz"

    def test_checkpoint_sans_objet(self) -> None:
        if not DEFAULT_PATH.exists():
            pytest.skip("checkpoint tête absent")
        arrays, cfg = load_checkpoint(DEFAULT_PATH)
        assert all(a.dtype != object for a in arrays.values())
        assert cfg["format"] == head_predict.FORMAT
        assert {"sec_coef", "sec_intercept"} <= set(arrays)

    def test_pickle_refuse(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.npz"
        np.savez(bad, config=np.array("{}"), coef=np.array([{"x": 1}], dtype=object))
        with pytest.raises(ValueError):
            load_checkpoint(bad)

    def test_save_refuse_objet(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            save_checkpoint(tmp_path / "x.npz", {"a": np.array([object()])}, {})

    def test_aller_retour(self, tmp_path: Path) -> None:
        out = tmp_path / "essai"
        save_checkpoint(out, {"a": np.arange(3), "v": np.array(["ab", "c"]), "n": None}, {"k": 1})
        # pas de .npz ajouté
        arrays, cfg = load_checkpoint(out)
        assert arrays["a"].tolist() == [0, 1, 2]
        assert arrays["v"].tolist() == ["ab", "c"]
        assert "n" not in arrays and cfg == {"k": 1}


class TestRapports:
    """essai : rien d'écrasé."""

    def test_defaut_versionne(self) -> None:
        meta, conflicts = head_train.report_paths(head_train.OUT)
        assert meta == head_train.OUT.parent / "meta.json"
        assert conflicts == head_train.CONFLICTS_OUT

    def test_essai_a_cote(self, tmp_path: Path) -> None:
        meta, conflicts = head_train.report_paths(tmp_path / "essai.npz")
        assert meta == tmp_path / "essai_meta.json"
        assert conflicts == tmp_path / "essai_conflicts.json"


class TestSecondaires:
    """étiquettes secondaires du train."""

    def test_label_set(self) -> None:
        g = Group(text="x", label="pricing")
        g.votes.update({"pricing": 2})
        g.pairs.update({("pricing", "payment_question"): 2})
        assert g.label_set() == ["pricing", "payment_question"]

    def test_secondaire_minoritaire_ignore(self) -> None:
        g = Group(text="x", label="greeting")
        g.votes.update({"greeting": 3})
        g.pairs.update({("greeting", "small_talk"): 1, ("faq", "pricing"): 3})
        assert g.label_set() == ["greeting"]


class TestMulti:
    """deux demandes, deux intentions."""

    @pytest.mark.parametrize(
        ("texte", "attendus"),
        [
            ("C'est combien une couleur et vous acceptez la CB ?", {"pricing", "payment_question"}),
            ("Je veux régler ma facture et suivre ma commande", {"payment", "order_status"}),
            (
                "Vous avez des créneaux vendredi ? Je voudrais prendre rdv",
                {"planning", "appointment"},
            ),
        ],
    )
    def test_deux_demandes(self, head, texte, attendus) -> None:
        res = head.predict_multi(texte)
        assert attendus <= {d["intent"] for d in res["intents"]}, res
        assert res["is_multi_intent"] is True
        # le moteur compte >= 0,35
        assert all(d["confidence"] >= 0.35 for d in res["intents"])

    def test_sonde_hors_gabarits(self, head) -> None:
        rows = load_rows(PROBE)
        preds = head.predict_batch_multi([r["text"] for r in rows])
        multi = [p for r, p in zip(rows, preds, strict=True) if len(labels_of(r)) > 1]
        single = [p for r, p in zip(rows, preds, strict=True) if len(labels_of(r)) == 1]
        # mesuré : 50 % (lstm 27 %)
        assert 100 * sum(p["is_multi_intent"] for p in multi) / len(multi) >= 40.0
        assert 100 * sum(p["is_multi_intent"] for p in single) / len(single) <= 5.0

    @pytest.mark.parametrize(
        "texte",
        [
            "bjr",
            "mon colis n'est pas arrivé",
            "je veux parler à un conseiller",
            "Combien coûte une coupe homme ?",
            "Vous avez de la place jeudi ?",
        ],
    )
    def test_simple_reste_simple(self, head, texte) -> None:
        assert head.predict_multi(texte)["is_multi_intent"] is False

    def test_confiances_triees(self, head) -> None:
        res = head.predict_multi("Je voudrais un rdv samedi et savoir si vous prenez la CB")
        confs = [d["confidence"] for d in res["intents"]]
        assert confs == sorted(confs, reverse=True)
        assert len(res["intents"]) <= 2

    def test_top1_inchange(self, head, test_rows) -> None:
        # même tête sans secondaires
        plain = EmbeddingIntentPredictor(
            head.encoder,
            head.coef,
            head.intercept,
            temperature=head.temperature,
            labels=head.labels,
            chars=head.chars,
            char_coef=head.char_coef,
        )
        texts = [r["text"] for r in test_rows[:150]]
        a = [p["primary_intent"] for p in head.predict_batch_multi(texts)]
        b = [p["primary_intent"] for p in plain.predict_batch_multi(texts)]
        assert a == b

    def test_rappel_multi_test(self, head, test_rows) -> None:
        preds = head.predict_batch_multi([r["text"] for r in test_rows])
        multi = [p for r, p in zip(test_rows, preds, strict=True) if len(labels_of(r)) > 1]
        single = [p for r, p in zip(test_rows, preds, strict=True) if len(labels_of(r)) == 1]
        rappel = 100 * sum(p["is_multi_intent"] for p in multi) / len(multi)
        faux = 100 * sum(p["is_multi_intent"] for p in single) / len(single)
        assert rappel >= RAPPEL_MULTI_MIN
        assert faux <= FAUX_MULTI_MAX
