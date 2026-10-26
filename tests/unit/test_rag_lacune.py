"""Lacune de connaissance : synonymes, flexions, sujets absents, seuils."""

from __future__ import annotations

import pytest

from jenny.engine import intelligence as intel
from jenny.engine.intelligence import (
    GAP_SCORE_FLOOR,
    GAP_SCORE_HARD_FLOOR,
    GAP_SCORE_STRONG,
    _retrieval_has_answer,
    _subject_uncovered,
    gap_verdict,
    is_knowledge_gap,
)
from jenny.rag.lexique import STOPWORDS, keys, stem


def _doc(content: str, score: float = 0.5, title: str = "") -> dict:
    return {"content": content, "score": score, "metadata": {"title": title}}


@pytest.mark.parametrize(
    ("question", "doc"),
    [
        ("Le brushing est-il compris ?", "Le brushing est inclus dans la coupe femme."),
        ("Le brushing est inclus ?", "La coupe comprend le brushing."),
        ("Y a-t-il des frais si j'annule ?", "Toute annulation tardive est facturée."),
        ("Je peux annuler ?", "Annulation gratuite jusqu'à 24 h avant."),
        ("Vous êtes ouverts le samedi ?", "Horaires : le samedi de 9h à 18h."),
        ("Quels sont vos horaires le jeudi ?", "Le jeudi, le salon reste ouvert jusqu'à 21h."),
        ("Le diagnostic est payant ?", "Le diagnostic couleur est offert."),
        ("Vous prenez la CB ?", "Paiement par carte bancaire ou espèces."),
        ("Vous coiffez les gamins ?", "Les enfants sont les bienvenus dès 3 ans."),
        ("Bonjour, merci ! Le brushing est compris svp ?", "Le brushing est inclus."),
    ],
)
def test_synonymes_pas_de_fausse_lacune(question: str, doc: str) -> None:
    docs = [_doc(doc, 0.5)]
    assert not _subject_uncovered(question, docs)
    assert not is_knowledge_gap(intent="faq", documents=docs, action_result=None, message=question)


def test_flexions_meme_racine() -> None:
    assert stem("annulation") == stem("annuler") == stem("annulée")
    assert stem("facturée") == stem("facturé") == stem("factures")
    assert stem("prévenir") == stem("prévenez")


def test_service_absent_est_une_lacune_meme_score_haut() -> None:
    docs = [_doc("Coiffure de mariée : chignons et accessoires.", 0.70, "Coiffure de mariée")]
    msg = "Faites-vous le maquillage de la mariée ?"
    assert is_knowledge_gap(intent="faq", documents=docs, action_result=None, message=msg)
    assert gap_verdict(docs, msg)[1] == "topic_missing"


def test_bande_sujet_non_couvert() -> None:
    docs = [_doc("Les cartes cadeaux sont valables 12 mois.", 0.45)]
    assert is_knowledge_gap(
        intent="faq", documents=docs, action_result=None, message="Vous louez des robes de soirée ?"
    )


def test_score_fort_fonde_avec_couverture_partielle() -> None:
    docs = [_doc("Station Voltaire (ligne 9) à 3 minutes.", 0.80, "Venir en métro")]
    ok, reason, top = gap_verdict(docs, "Quelle est la station de métro la plus proche ?")
    assert ok
    assert reason == "strong"
    assert top == pytest.approx(0.80)


def test_sous_le_plancher_lacune() -> None:
    docs = [_doc("Le brushing est inclus.", GAP_SCORE_HARD_FLOOR - 0.01)]
    assert not _retrieval_has_answer(docs, "Le brushing est inclus ?")
    assert gap_verdict(docs, "Le brushing est inclus ?")[1] == "below_floor"


def test_seuils_coherents_et_noms_stables() -> None:
    assert GAP_SCORE_FLOOR == GAP_SCORE_HARD_FLOOR
    assert 0 < GAP_SCORE_HARD_FLOOR < GAP_SCORE_STRONG < 1
    # une seule liste de mots vides
    assert intel._SUBJECT_STOPWORDS is STOPWORDS


def test_seuils_surchargeables() -> None:
    docs = [_doc("Le brushing est inclus.", 0.5)]
    assert gap_verdict(docs, "brushing compris ?", floor=0.6)[1] == "below_floor"
    assert gap_verdict(docs, "brushing compris ?", strong=0.45)[1] == "strong"


def test_journal_du_top_score(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _Log:
        def info(self, event: str, **kw) -> None:
            calls.append((event, kw))

    monkeypatch.setattr(intel, "logger", _Log())
    is_knowledge_gap(
        intent="faq", documents=[_doc("x", 0.42)], action_result=None, message="Le wifi ?"
    )
    event, kw = calls[-1]
    assert event == "intelligence.gap_decision"
    assert kw["top_score"] == pytest.approx(0.42)
    assert kw["reason"]
    assert kw["gap"] is True


def test_concepts_lexique() -> None:
    assert "inclus" in keys("compris")
    assert "annulation" in keys("décommander")
    # un mot, plusieurs concepts
    assert {"cout", "paiement"} <= keys("payer")
