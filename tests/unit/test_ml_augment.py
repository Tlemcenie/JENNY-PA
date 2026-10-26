"""augmentation et n-grammes de la tête."""

import numpy as np

from ml.models.intent_head.augment import (
    perturb_eval,
    perturb_unseen,
    plain,
    sms,
    variants,
)
from ml.models.intent_head.data import Group, frozen_split, norm_key
from ml.models.intent_head.features import CharNgrams, char_grams


class TestAugment:
    """bruit de surface déterministe."""

    def test_plain(self) -> None:
        assert plain("Bonjour, ça va ?!") == "bonjour ca va"

    def test_sms_mots_entiers(self) -> None:
        assert sms("bonjour je veux un rendez-vous pour demain") == "bjr je veux un rdv pr demain"
        # pas dans les mots
        assert sms("pourquoi") == "pourquoi"

    def test_variants_deterministes(self) -> None:
        texte = "Bonjour, je voudrais un rendez-vous pour une coupe s'il vous plaît"
        assert variants(texte) == variants(texte)
        out = variants(texte)
        assert out[0] == texte
        assert len(out) == len(set(out))
        assert any("rdv" in v and "svp" in v for v in out)

    def test_perturb_eval_reference(self) -> None:
        # identique à l'ancien script
        assert perturb_eval("Bonjour ! Combien pour un rendez-vous ?") == "bjr  cbien pr un rdv "

    def test_inedit_hors_train(self) -> None:
        out = perturb_unseen("Je voudrais savoir si vous êtes ouvert aujourd'hui")
        assert out == "jvoudrais savoir si vs etes ouvert ajd"
        # formes absentes du train
        for v in variants("Je voudrais savoir si vous êtes ouvert aujourd'hui"):
            assert "jvoudrais" not in v and " vs " not in v


class TestData:
    """split figé et doublons."""

    def test_split_identique_lstm(self) -> None:
        s = frozen_split(5061)
        assert [len(s[k]) for k in ("train", "val", "test")] == [3542, 759, 760]
        assert s["test"][:5] == [3707, 5026, 5058, 185, 2449]
        assert not set(s["train"]) & set(s["test"])

    def test_cle_doublon(self) -> None:
        assert norm_key("Prix d'une coupe ?") == norm_key("prix d une coupe")

    def test_egalite(self) -> None:
        g = Group(text="x")
        g.votes.update({"pricing": 1, "quote": 1})
        assert g.conflict
        assert g.tied() == ["pricing", "quote"]


class TestCharNgrams:
    """tf-idf maison."""

    def test_grams_bordes(self) -> None:
        assert char_grams("Été", 2, 3) == [" e", "et", "te", "e ", " et", "ete", "te "]

    def test_fit_transform(self) -> None:
        textes = ["prix coupe", "prix couleur", "rdv demain", "rdv coupe"]
        ch = CharNgrams().fit(textes, min_df=2)
        assert len(ch) > 0
        m = ch.transform(textes).toarray()
        assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)
        # même calcul en dense
        coef = np.random.default_rng(0).normal(size=(3, len(ch))).astype(np.float32)
        assert np.allclose(ch.logits(coef, textes), m @ coef.T, atol=1e-5)

    def test_texte_vide(self) -> None:
        ch = CharNgrams().fit(["aa bb", "aa cc"], min_df=1)
        assert ch.transform([""]).nnz == 0
        assert np.all(ch.logits(np.ones((2, len(ch)), np.float32), [""]) == 0)
