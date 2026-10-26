"""presta du ner contre le catalogue."""

import pytest

from jenny.engine.ner_guard import catalog_service

# catalogue de seed-coiffeur
SALON = [
    "Coupe femme",
    "Coupe homme",
    "Brushing",
    "Coloration",
    "Balayage",
    "Soin profond",
    "Barbe",
]


class TestConnue:
    """une seule presta possible."""

    @pytest.mark.parametrize(
        ("valeur", "attendu"),
        [
            ("coupe homme", "Coupe homme"),
            ("Coupe Femme", "Coupe femme"),
            ("une coupe femme courte", "Coupe femme"),
            ("balayage", "Balayage"),
            ("balyage", "Balayage"),
            ("colo", "Coloration"),
            ("soin", "Soin profond"),
            ("brushings", "Brushing"),
            ("barbe", "Barbe"),
        ],
    )
    def test_resolue(self, valeur, attendu) -> None:
        assert catalog_service(valeur, SALON) == attendu

    def test_plusieurs(self) -> None:
        assert catalog_service("coupe femme et coloration", SALON) == "Coupe femme et Coloration"

    def test_doublon(self) -> None:
        assert catalog_service("balayage et balyage", SALON) == "Balayage"


class TestInconnue:
    """hors catalogue ou ambiguë."""

    @pytest.mark.parametrize(
        "valeur",
        ["lissage brésilien", "extension de cils", "manucure", "massage capillaire", "tatouage"],
    )
    def test_hors_catalogue(self, valeur) -> None:
        assert catalog_service(valeur, SALON) is None

    def test_coupe_seule_ambigue(self) -> None:
        # femme ou homme ?
        assert catalog_service("coupe", SALON) is None

    def test_une_seule_coupe(self) -> None:
        assert catalog_service("coupe", ["Coupe", "Barbe"]) == "Coupe"

    def test_le_plus_precis(self) -> None:
        assert catalog_service("coupe femme", ["Coupe", "Coupe femme"]) == "Coupe femme"

    def test_une_partie_inconnue(self) -> None:
        # on ne garde pas la moitié
        assert catalog_service("coupe homme et lissage brésilien", SALON) is None

    @pytest.mark.parametrize("catalogue", [None, []])
    def test_sans_catalogue(self, catalogue) -> None:
        assert catalog_service("coupe homme", catalogue) is None

    @pytest.mark.parametrize("valeur", [None, "", "   "])
    def test_vide(self, valeur) -> None:
        assert catalog_service(valeur, SALON) is None

    def test_homme_pas_femme(self) -> None:
        assert catalog_service("coupe homme", ["Coupe femme", "Brushing"]) is None
