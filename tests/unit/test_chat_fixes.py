"""Non-régression des correctifs chat (nom, horaires, catalogue)."""
from __future__ import annotations

from jenny.actions.handlers.set_customer_name import _clean_name
from jenny.engine.business_hours import format_hours
from jenny.engine.conversation_engine import looks_like_name


class TestNomAvecPrefixe:
    """« c'est pour X » doit être vu comme un nom (bug capture RDV)."""

    def test_nom_simple(self) -> None:
        assert looks_like_name("Camille Durand")

    def test_cest_pour(self) -> None:
        assert looks_like_name("C'est pour Camille Durand")

    def test_je_mappelle(self) -> None:
        assert looks_like_name("je m'appelle Léa")

    def test_au_nom_de(self) -> None:
        assert looks_like_name("au nom de Marie Dupont")

    def test_pronom_refuse(self) -> None:
        assert not looks_like_name("c'est pour moi")

    def test_prefixe_seul_refuse(self) -> None:
        assert not looks_like_name("c'est pour")

    def test_question_refuse(self) -> None:
        assert not looks_like_name("c'est quoi vos prix ?")


class TestNettoyageNom:
    """Le préfixe doit être retiré du nom stocké (pas « Pour Camille »)."""

    def test_cest_pour(self) -> None:
        assert _clean_name("C'est pour Camille Durand") == "Camille Durand"

    def test_au_nom_de(self) -> None:
        assert _clean_name("au nom de Jean Dupont") == "Jean Dupont"

    def test_pour_seul(self) -> None:
        assert _clean_name("pour Sophie") == "Sophie"

    def test_moi_cest(self) -> None:
        assert _clean_name("moi c'est Karim") == "Karim"


class TestHoraires:
    """Les horaires réels doivent partir dans le prompt (anti-hallucination)."""

    def test_defaut_dimanche_ferme(self) -> None:
        out = format_hours(None)
        assert "dimanche fermé" in out

    def test_jour_ferme_et_ouvert(self) -> None:
        out = format_hours(
            {"mon": None, "tue": ["09:00", "19:00"], "thu": ["09:00", "21:00"], "sun": None}
        )
        assert "lundi fermé" in out
        assert "mardi 09:00-19:00" in out
        assert "jeudi 09:00-21:00" in out
