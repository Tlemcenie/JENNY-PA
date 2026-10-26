"""tests des dates FR."""

from datetime import date, datetime, time

import pytest

from jenny.engine.datetime_fr import (
    combine_fr,
    format_fr_date,
    format_fr_time,
    parse_fr_date,
    parse_fr_duration,
    parse_fr_time,
    to_hhmm,
    to_iso_date,
)

LUNDI = date(2026, 10, 26)
MERCREDI = date(2026, 10, 28)
SAMEDI = date(2026, 10, 31)
DIMANCHE = date(2026, 11, 1)
FIN_ANNEE = date(2026, 12, 30)  # mercredi


def d(text: str, today: date = LUNDI) -> date | None:
    return parse_fr_date(text, today=today)


class TestIsoEtCompat:
    """contrat avec les handlers"""

    def test_iso_date(self) -> None:
        assert d("2026-10-29") == date(2026, 10, 29)

    def test_iso_passee_gardee(self) -> None:
        # iso = absolu, pas de report
        assert d("2026-01-02") == date(2026, 1, 2)

    def test_iso_invalide(self) -> None:
        assert d("2026-13-01") is None
        assert d("2026-02-30") is None

    def test_iso_datetime(self) -> None:
        assert d("2026-10-29T14:00") == date(2026, 10, 29)
        assert parse_fr_time("2026-10-29T14:00") == time(14, 0)

    def test_hhmm(self) -> None:
        assert parse_fr_time("14:00") == time(14, 0)
        assert parse_fr_time("09:30") == time(9, 30)

    def test_aller_retour(self) -> None:
        iso = to_iso_date("jeudi prochain", today=MERCREDI)
        assert iso == "2026-11-05"
        assert d(iso, today=date(2026, 11, 1)) == date(2026, 11, 5)
        assert to_hhmm("14h30") == "14:30"
        assert parse_fr_time(to_hhmm("midi")) == time(12, 0)

    def test_texte_libre_toujours_ok(self) -> None:
        assert d("demain") == date(2026, 10, 27)
        assert parse_fr_time("14h") == time(14, 0)

    def test_vide(self) -> None:
        assert parse_fr_date("") is None
        assert parse_fr_time("") is None
        assert to_iso_date("bonjour") is None
        assert to_hhmm("bonjour") is None


class TestJoursRelatifs:
    def test_demain(self) -> None:
        assert d("demain") == date(2026, 10, 27)
        assert d("Demain matin") == date(2026, 10, 27)

    def test_apres_demain(self) -> None:
        assert d("après-demain") == date(2026, 10, 28)
        assert d("apres demain") == date(2026, 10, 28)

    def test_aujourdhui(self) -> None:
        assert d("aujourd'hui") == LUNDI
        assert d("aujourd’hui") == LUNDI  # noqa: RUF001
        assert d("ce soir") == LUNDI
        assert d("cet après-midi") == LUNDI

    def test_lendemain_pas_demain(self) -> None:
        assert d("le lendemain") is None

    def test_demain_fin_annee(self) -> None:
        assert d("demain", today=date(2026, 12, 31)) == date(2027, 1, 1)


class TestJoursSemaine:
    def test_jour_simple(self) -> None:
        assert d("jeudi") == date(2026, 10, 29)
        assert d("jeudi", today=MERCREDI) == date(2026, 10, 29)

    def test_aujourdhui_compte(self) -> None:
        assert d("lundi") == LUNDI

    def test_jeudi_prochain_un_mercredi(self) -> None:
        # pas demain : la semaine suivante
        assert d("jeudi prochain", today=MERCREDI) == date(2026, 11, 5)

    def test_prochain_semaine_suivante(self) -> None:
        assert d("jeudi prochain") == date(2026, 11, 5)
        assert d("lundi prochain") == date(2026, 11, 2)
        assert d("samedi prochain", today=SAMEDI) == date(2026, 11, 7)

    def test_semaine_prochaine_avec_jour(self) -> None:
        assert d("mardi de la semaine prochaine") == date(2026, 11, 3)
        assert d("la semaine prochaine, mardi") == date(2026, 11, 3)

    def test_en_huit(self) -> None:
        assert d("mardi en huit") == date(2026, 11, 3)
        assert d("demain en huit") == date(2026, 11, 3)

    def test_jour_et_numero(self) -> None:
        assert d("jeudi 29") == date(2026, 10, 29)
        assert d("mardi 3") == date(2026, 11, 3)

    def test_jour_et_heure(self) -> None:
        # « lundi 14h » : pas le 14
        assert d("lundi 14h", today=MERCREDI) == date(2026, 11, 2)

    def test_prochain_passe_l_annee(self) -> None:
        assert d("lundi prochain", today=FIN_ANNEE) == date(2027, 1, 4)
        assert d("vendredi", today=FIN_ANNEE) == date(2027, 1, 1)


class TestMois:
    def test_jour_mois(self) -> None:
        assert d("le 14 février") == date(2027, 2, 14)
        assert d("3 mars") == date(2027, 3, 3)
        assert d("le 1er mars") == date(2027, 3, 1)
        assert d("jeudi 29 octobre") == date(2026, 10, 29)

    def test_abreviations(self) -> None:
        assert d("le 3 sept.") == date(2027, 9, 3)
        assert d("12 déc") == date(2026, 12, 12)
        assert d("5 janv") == date(2027, 1, 5)

    def test_annee_explicite(self) -> None:
        assert d("14 février 2028") == date(2028, 2, 14)

    def test_date_passee_annee_suivante(self) -> None:
        assert d("le 25 octobre") == date(2027, 10, 25)
        assert d("le 26 octobre") == LUNDI

    def test_29_fevrier(self) -> None:
        # 2027 non bissextile → 2028
        assert d("29 février") == date(2028, 2, 29)
        assert d("29 février", today=date(2028, 1, 10)) == date(2028, 2, 29)
        assert d("29 février 2027") is None
        assert d("29 février 2028") == date(2028, 2, 29)

    def test_date_impossible(self) -> None:
        assert d("31 avril") is None
        assert d("30 février") is None

    def test_fin_annee(self) -> None:
        assert d("le 2 janvier", today=FIN_ANNEE) == date(2027, 1, 2)
        assert d("le 31 décembre", today=FIN_ANNEE) == date(2026, 12, 31)

    def test_ancres(self) -> None:
        assert d("début mars") == date(2027, 3, 1)
        assert d("mi-mars") == date(2027, 3, 15)
        assert d("mi mars") == date(2027, 3, 15)
        assert d("fin mars") == date(2027, 3, 25)
        assert d("en août") == date(2027, 8, 1)
        assert d("au mois d'août") == date(2027, 8, 1)
        assert d("courant novembre") == date(2026, 11, 1)
        assert d("fin février", today=date(2028, 1, 5)) == date(2028, 2, 23)

    def test_ancre_mois_courant(self) -> None:
        # jamais dans le passé
        assert d("fin octobre") == LUNDI
        assert d("début octobre") == LUNDI
        assert d("fin du mois", today=date(2026, 10, 2)) == date(2026, 10, 25)

    def test_mois_prochain(self) -> None:
        assert d("le mois prochain") == date(2026, 11, 1)
        assert d("fin du mois prochain") == date(2026, 11, 24)
        assert d("le mois prochain", today=FIN_ANNEE) == date(2027, 1, 1)


class TestNumerique:
    def test_jj_mm(self) -> None:
        assert d("le 14/02") == date(2027, 2, 14)
        assert d("14/02/2027") == date(2027, 2, 14)
        assert d("14-02-27") == date(2027, 2, 14)
        assert d("1.2.2027") == date(2027, 2, 1)

    def test_jj_mm_passe(self) -> None:
        assert d("25/10") == date(2027, 10, 25)
        assert d("26/10") == LUNDI

    def test_29_02(self) -> None:
        assert d("29/02") == date(2028, 2, 29)
        assert d("29/02/2027") is None

    def test_pas_un_prix(self) -> None:
        assert d("12.10 €") is None
        assert d("ça fait 12.10 ?") is None

    def test_pas_une_plage_horaire(self) -> None:
        assert d("10-12h") is None

    def test_pas_un_telephone(self) -> None:
        assert d("06/12/34/56/78") is None
        assert d("06-12-34-56-78") is None
        assert d("le 06 12 34 56 78") is None


class TestRelatifs:
    def test_dans_n_jours(self) -> None:
        assert d("dans 3 jours") == date(2026, 10, 29)
        assert d("dans trois jours") == date(2026, 10, 29)

    def test_quinze_jours_deux_semaines(self) -> None:
        assert d("dans 15 jours") == date(2026, 11, 9)
        assert d("dans quinze jours") == date(2026, 11, 9)
        assert d("dans 8 jours") == date(2026, 11, 2)

    def test_semaines_mois(self) -> None:
        assert d("dans 2 semaines") == date(2026, 11, 9)
        assert d("dans une semaine") == date(2026, 11, 2)
        assert d("dans un mois") == date(2026, 11, 26)
        assert d("dans un mois", today=date(2027, 1, 31)) == date(2027, 2, 28)

    def test_dans_passe_annee(self) -> None:
        assert d("dans 5 jours", today=FIN_ANNEE) == date(2027, 1, 4)

    def test_week_end(self) -> None:
        assert d("ce week-end") == SAMEDI
        assert d("ce weekend", today=MERCREDI) == SAMEDI
        assert d("ce week-end", today=SAMEDI) == SAMEDI
        assert d("ce week-end", today=DIMANCHE) == DIMANCHE

    def test_week_end_prochain(self) -> None:
        assert d("le week-end prochain") == date(2026, 11, 7)
        assert d("le prochain week-end", today=SAMEDI) == date(2026, 11, 7)

    def test_semaine_prochaine(self) -> None:
        assert d("la semaine prochaine") == date(2026, 11, 2)
        assert d("la semaine prochaine", today=DIMANCHE) == date(2026, 11, 2)
        assert d("cette semaine", today=MERCREDI) == MERCREDI

    def test_en_semaine_pas_une_date(self) -> None:
        assert d("vous êtes ouverts en semaine ?") is None

    def test_le_14(self) -> None:
        assert d("le 14") == date(2026, 11, 14)
        assert d("le 30 à 14h") == date(2026, 10, 30)
        assert d("le 31", today=date(2026, 11, 5)) == date(2026, 12, 31)
        assert d("le 1er", today=FIN_ANNEE) == date(2027, 1, 1)

    def test_le_14_pas_une_adresse(self) -> None:
        assert d("au 12 rue de Paris") is None
        assert d("le 14h") is None
        assert d("pour le 2 personnes") is None


class TestNegation:
    def test_pas_demain(self) -> None:
        assert d("pas demain mais jeudi") == date(2026, 10, 29)
        assert d("je ne peux pas demain") is None

    def test_negation_apres(self) -> None:
        assert d("demain c'est pas possible, vendredi ?") == date(2026, 10, 30)

    def test_pas_avant(self) -> None:
        # « pas avant jeudi » = jeudi ok
        assert d("pas avant jeudi") == date(2026, 10, 29)


class TestHeures:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("14h", time(14, 0)),
            ("14h30", time(14, 30)),
            ("14 h 30", time(14, 30)),
            ("14:30", time(14, 30)),
            ("14 heures", time(14, 0)),
            ("9h", time(9, 0)),
            ("11h45", time(11, 45)),
            ("midi", time(12, 0)),
            ("vers midi", time(12, 0)),
            ("ce midi", time(12, 0)),
            ("midi et demi", time(12, 30)),
            ("midi et demie", time(12, 30)),
            ("midi moins le quart", time(11, 45)),
            ("midi 30", time(12, 30)),
            ("minuit", time(0, 0)),
            ("minuit moins le quart", time(23, 45)),
            ("14h et quart", time(14, 15)),
            ("9h et demie", time(9, 30)),
            ("15h moins le quart", time(14, 45)),
            ("2h de l'après-midi", time(14, 0)),
            ("8h du soir", time(20, 0)),
            ("10h du matin", time(10, 0)),
            ("à 14", time(14, 0)),
            ("vers 15 ?", time(15, 0)),
            ("rendez-vous à 9 svp", time(9, 0)),
        ],
    )
    def test_formes(self, text: str, expected: time) -> None:
        assert parse_fr_time(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "cet après-midi",
            "dans 2h",
            "ça dure 1h30 ?",
            "il faut compter 2h",
            "il y a 10 coiffeurs",
            "à 10 km",
            "c'est à 20 euros ?",
            "à 25",
            "24h/24",
            "14 habitants",
            "bonjour",
        ],
    )
    def test_pas_une_heure(self, text: str) -> None:
        assert parse_fr_time(text) is None

    def test_premiere_heure_citee(self) -> None:
        assert parse_fr_time("à midi ou 14h") == time(12, 0)
        assert parse_fr_time("14h-16h") == time(14, 0)

    def test_negation(self) -> None:
        assert parse_fr_time("pas 14h, plutôt 16h") == time(16, 0)

    def test_avec_date(self) -> None:
        assert parse_fr_time("le 14 à 15h") == time(15, 0)


class TestDurees:
    @pytest.mark.parametrize(
        ("text", "minutes"),
        [
            ("30 min", 30),
            ("30 minutes", 30),
            ("45", 45),
            ("1h", 60),
            ("1h30", 90),
            ("1 h 30", 90),
            ("une heure", 60),
            ("deux heures", 120),
            ("une demi-heure", 30),
            ("1h et demie", 90),
        ],
    )
    def test_formes(self, text: str, minutes: int) -> None:
        assert parse_fr_duration(text) == minutes

    @pytest.mark.parametrize("text", ["", "3 jours", "beaucoup", "2", "5000 min"])
    def test_invalides(self, text: str) -> None:
        assert parse_fr_duration(text) is None


class TestCombine:
    def test_iso(self) -> None:
        now = datetime(2026, 10, 26, 23, 59)
        assert combine_fr("2026-10-27", "14:00", now=now) == datetime(2026, 10, 27, 14, 0)

    def test_minuit_passe(self) -> None:
        # date figée : minuit sans effet
        before = combine_fr("2026-10-27", "10:00", now=datetime(2026, 10, 26, 23, 59))
        after = combine_fr("2026-10-27", "10:00", now=datetime(2026, 10, 27, 0, 1))
        assert before == after

    def test_heure_par_defaut(self) -> None:
        now = datetime(2026, 10, 26, 9, 0)
        assert combine_fr("demain", None, now=now) == datetime(2026, 10, 27, 10, 0)

    def test_date_floue(self) -> None:
        assert combine_fr("bientôt", "14h") is None

    def test_fuseau(self) -> None:
        assert combine_fr("2026-10-27", "9h", tz="America/New_York") == datetime(2026, 10, 27, 9, 0)


class TestAffichage:
    def test_date_en_clair(self) -> None:
        assert format_fr_date("2026-10-29", today=LUNDI) == "jeudi 29 octobre"
        assert format_fr_date(date(2027, 2, 14), today=LUNDI) == "dimanche 14 février 2027"
        assert format_fr_date("demain", today=LUNDI) == "mardi 27 octobre"
        assert format_fr_date("bientôt") is None
        assert format_fr_date(None) is None

    def test_heure_en_clair(self) -> None:
        assert format_fr_time("14:00") == "14h"
        assert format_fr_time("09:30") == "9h30"
        assert format_fr_time(time(12, 5)) == "12h05"
        assert format_fr_time("") is None
