"""Passe 3 : règle STOP, la négation doit viser le STOP lui-même."""

from __future__ import annotations

import inspect

import pytest

from jenny.services.offer_cap import apply_stop_reply, is_stop_reply

# refus clairs : STOP
OUI = [
    # déjà vrais avant
    "STOP",
    "stop",
    "Stop.",
    "STOP 🛑",
    "Arrêtez",
    "désinscription",
    "Désinscrivez-moi svp",
    "unsubscribe",
    "je ne veux plus recevoir vos offres, merci",
    "ne m'envoyez plus de messages",
    "Plus de pub svp",
    "pas de sms",
    "arrêtez de m'envoyer des messages",
    "vous pouvez arrêter",
    # cassés avant (un « pas » ailleurs)
    "je ne veux pas de pub, stop",
    "stop, ne m'envoyez pas de messages",
    "Stop, pas de pub",
    "stop pas de pub",
    "STOP je ne veux pas de SMS",
    "STOP! Pas de pub",
    "je ne souhaite pas recevoir vos offres",
    "Ne m'envoyez pas de pub",
    "je ne veux pas recevoir de sms",
    "merci de ne pas m'écrire",
    "désinscrivez-moi, pas de pub",
    "je ne veux pas, stop",
    "Non merci, stop",
    "plus jamais de messages svp",
    "jamais de pub",
    "désabonne-moi",
    "pouvez-vous stopper les messages",
]

# la négation porte sur le STOP
NON = [
    "n'arrêtez pas",
    "N'arrêtez pas !",
    "arrête pas",
    "arrêtez pas de m'envoyer des messages",
    "n'arrêtez pas de m'envoyer des offres",
    "n'arrêtez jamais",
    "ne me désinscrivez pas",
    "ne me désabonne pas",
    "je ne veux pas me désinscrire",
    "je ne veux pas arrêter",
    "ne pas me désinscrire",
    "ne stoppez pas les messages",
    "pas stop",
    "pas de stop",
    "jamais stop",
    "stop pas",
    # pas un refus
    "envoyez-moi plus d'offres",
    "envoyez-moi des offres",
    "je veux des offres",
    "ok merci",
    "plus",
]

# ambigu : la conversation répond
AMBIGU = [
    "",
    None,
    "   ",
    "stop ? pas du tout",
    "stop je voulais dire jeudi",
    "stop au bruit chez vous",
    "STOP 2",
    "je veux arrêter la coloration",
    "je ne veux pas",
    "pas",
    "pas maintenant",
    "pas de souci",
    "je ne suis pas intéressée",
    "je n'ai pas dit stop",
    "stop " + "svp " * 20,
]


@pytest.mark.parametrize("txt", OUI)
def test_refus_clair(txt: str) -> None:
    assert is_stop_reply(txt), txt


@pytest.mark.parametrize("txt", NON)
def test_negation_du_stop(txt: str) -> None:
    assert not is_stop_reply(txt), txt


@pytest.mark.parametrize("txt", AMBIGU)
def test_ambigu(txt: str | None) -> None:
    assert not is_stop_reply(txt), txt


def test_signatures_gardees() -> None:
    assert list(inspect.signature(is_stop_reply).parameters) == ["text"]
    params = inspect.signature(apply_stop_reply).parameters
    assert list(params) == ["db", "business_id", "customer_id", "text", "conversation_id"]
    assert inspect.iscoroutinefunction(apply_stop_reply)
