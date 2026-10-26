"""Relances passe 2 : règle STOP, prénoms piégés, textes sans fuite."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jenny.services.campaigns import first_name, render_message
from jenny.services.gap_filler import Candidate, catalogue_label, offer_text
from jenny.services.offer_cap import STOP_ACK, is_stop_reply
from jenny.services.relances_loop import loop_enabled


class TestStopRule:
    @pytest.mark.parametrize(
        "txt",
        [
            "STOP",
            "stop",
            "Stop.",
            " stop svp ",
            "STOP 🛑",
            "Stop stop stop !!",
            "arrêt",
            "Arrêtez",
            "arrête",
            "désinscription",
            "Désinscrivez-moi svp",
            "Bonjour, STOP merci",
            "unsubscribe",
            "je ne veux plus recevoir vos offres, merci",
            "ne m'envoyez plus de messages",
            "Plus de pub svp",
            "pas de sms",
            "arrêtez de m'envoyer des messages",
            "vous pouvez arrêter",
        ],
    )
    def test_stop(self, txt: str) -> None:
        assert is_stop_reply(txt), txt

    @pytest.mark.parametrize(
        "txt",
        [
            "",
            None,
            "   ",
            "stop je voulais dire jeudi",
            "stop au bruit chez vous",
            "n'arrêtez pas",
            "envoyez-moi plus d'offres",
            "ok merci",
            "plus",
            "STOP 2",
            "je veux arrêter la coloration",
            "je voudrais un rdv jeudi",
            "stop " + "svp " * 20,
        ],
    )
    def test_ambigu_pas_stop(self, txt: str | None) -> None:
        assert not is_stop_reply(txt), txt

    def test_accuse_reception(self) -> None:
        # rappels toujours envoyés
        assert "plus d'offres" in STOP_ACK and "rappels" in STOP_ACK


class TestPrenomPiege:
    @pytest.mark.parametrize("name", ["\\o/ Lucie", "Lu\\cie", "\\1", "\\g<0>", "a\\"])
    def test_antislash_ne_plante_pas(self, name: str) -> None:
        out = render_message("Bonjour {prenom}, ça va ?", name=first_name(name), salon="S")
        assert out.startswith("Bonjour")
        # même brut, pas d'erreur
        raw = render_message("Coucou {prenom} !", name=name, salon="S")
        assert raw.startswith(f"Coucou {name} !")

    def test_prenom_sans_symboles(self) -> None:
        assert first_name("\\o/ Lucie") == ""
        assert first_name("Marie-Claire Dupont") == "Marie-Claire"
        assert first_name("zoé") == "Zoé"
        assert first_name("O'Neil") == "O'Neil"
        assert first_name("...") == ""


class TestPasDeTitreLibre:
    def test_offre_sans_label(self) -> None:
        c = Candidate(source="rebook", duration=30, service="RDV — Sophie Martin", name="Léa")
        txt = offer_text(c, salon="Salon", when="demain à 10h00", link=None)
        assert "Sophie" not in txt and "Martin" not in txt

    def test_offre_avec_label(self) -> None:
        c = Candidate(
            source="rebook",
            duration=30,
            service="Coloration Marie, a payé en retard",
            label="Coloration",
            name="Léa",
        )
        txt = offer_text(c, salon="Salon", when="demain à 10h00", link=None)
        assert "(Coloration)" in txt and "payé" not in txt

    def test_catalogue_label(self) -> None:
        cat = [SimpleNamespace(name="Coupe femme"), SimpleNamespace(name="Coloration")]
        assert catalogue_label(cat, "coloration Marie note interne") == "Coloration"
        assert catalogue_label(cat, "RDV — Sophie Martin") is None
        assert catalogue_label([], "Coupe") is None
        assert catalogue_label(cat, None) is None


class TestBoucleReglage:
    def test_coupee_en_test(self, monkeypatch) -> None:
        monkeypatch.setenv("JENNY_RELANCES_LOOP", "1")
        assert not loop_enabled(SimpleNamespace(env="test"))

    def test_env_et_defaut(self, monkeypatch) -> None:
        monkeypatch.delenv("JENNY_RELANCES_LOOP", raising=False)
        assert loop_enabled(SimpleNamespace(env="prod"))
        assert not loop_enabled(SimpleNamespace(env="prod", relances_loop_enabled=False))
        monkeypatch.setenv("JENNY_RELANCES_LOOP", "off")
        assert not loop_enabled(SimpleNamespace(env="dev"))
        monkeypatch.setenv("JENNY_RELANCES_LOOP", "true")
        assert loop_enabled(SimpleNamespace(env="prod", relances_loop_enabled=False))
