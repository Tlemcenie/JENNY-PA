"""passe 3 moteur : refus d'offre, « rechanger »."""

from __future__ import annotations

import time
from datetime import date

import pytest

from jenny.engine.conversation_engine import (
    _MGMT_RESCHED_RE,
    current_slots,
    detect_appointment_mgmt,
    keeps_current_slot,
)

TODAY = date(2026, 10, 26)  # lundi
BOOKED = ("2026-10-27", "10:00")


class TestRechanger:
    @pytest.mark.parametrize(
        "msg",
        [
            "je dois rechanger la date de mon rdv",
            "je voudrais rechanger l'heure",
            "Bonjour, je voudrais rechanger l'heure de mon rdv",
            "je peux rechanger de jour ?",
            "on peut échanger de jour ?",
            "je voudrais changer l'heure",
            "je veux changer la date",
            "Changer de jour, c'est possible ?",
        ],
    )
    def test_report(self, msg: str) -> None:
        assert detect_appointment_mgmt(msg, False) == "reschedule"

    @pytest.mark.parametrize(
        "msg", ["je veux changer de coiffeur", "c'est un échange", "rechange de shampoing"]
    )
    def test_pas_un_report(self, msg: str) -> None:
        assert detect_appointment_mgmt(msg, False) is None

    @pytest.mark.parametrize("body", ["rechang", "échang", "chang", "-chang", "rechang "])
    def test_lineaire(self, body: str) -> None:
        s = body * (10000 // len(body)) + "x"
        t0 = time.perf_counter()
        _MGMT_RESCHED_RE.search(s)
        assert time.perf_counter() - t0 < 0.05


class TestGardeSonRdv:
    @pytest.mark.parametrize(
        "msg",
        [
            "Non merci, je reste sur demain",
            "Tant pis, je garde demain alors, merci !",
            "Laissez tomber, demain c'est très bien",
            "Ah non pas après-demain finalement, je garde demain",
            "Tant pis, je garde demain 10h alors, merci !",
            "Bon, demain 10h ça me va très bien",
            "Je reste sur demain comme prévu",
            "on ne change rien",
            "Laissez tomber",
            "Non merci",
            # son jour, sans heure
            "demain alors",
            "Bon, demain finalement.",
            "je ne veux plus décaler",
            "pas la peine de déplacer",
        ],
    )
    def test_garde(self, msg: str) -> None:
        assert keeps_current_slot(msg, today=TODAY, booked=BOOKED)

    @pytest.mark.parametrize(
        "msg",
        [
            "Non, plutôt jeudi 15h",
            "et demain 16h ?",
            "non pas jeudi, vendredi plutôt",
            "mercredi 9h alors",
            "et demain ?",
            "ok",
            "16h ?",
            "pourquoi pas décaler à jeudi",
            "je voudrais plutôt décaler mon rdv",
        ],
    )
    def test_autre_creneau(self, msg: str) -> None:
        assert not keeps_current_slot(msg, today=TODAY, booked=BOOKED)

    def test_sans_rdv(self) -> None:
        # réservation ratée : pas de rdv
        assert keeps_current_slot("Non merci, je vais réfléchir", today=TODAY)
        assert not keeps_current_slot("Non, plutôt demain 15h", today=TODAY)
        assert not keeps_current_slot("Bon, demain 10h ça me va", today=TODAY)


class TestCreneauActuel:
    def test_fil_et_base(self) -> None:
        offer = {"operation": "reschedule", "success": False, "when": "mardi 27/10 à 09h00"}
        assert current_slots(offer, today=TODAY, booked=BOOKED) == [
            BOOKED,
            ("2026-10-27", "09:00"),
        ]

    def test_base_seule(self) -> None:
        offer = {"operation": "reschedule", "conflict": True, "when": "mardi 27/10 à 10h00"}
        assert current_slots(offer, today=TODAY) == [BOOKED]

    def test_sans_info(self) -> None:
        # résa ratée : pas de « when »
        assert current_slots({"conflict": True}, today=TODAY) == [(None, None)]
        # report réussi : nouveau créneau
        ok = {"operation": "reschedule", "success": True, "when": "jeudi 29/10 à 16h00"}
        assert current_slots(ok, today=TODAY) == [(None, None)]
        assert current_slots({}, today=TODAY, booked=BOOKED) == [BOOKED]
