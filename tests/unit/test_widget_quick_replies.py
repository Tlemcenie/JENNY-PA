"""Réponses rapides du widget."""

from jenny.api.routes.public_chat import quick_replies


def test_creneaux_proposes() -> None:
    txt = "Voici les créneaux libres samedi : 09 h 00, 09 h 30, 10 h 00 ou 10 h 30. Lequel ?"
    assert quick_replies(txt) == ["9h", "9h30", "10h", "10h30"]


def test_question_libre_sans_boutons() -> None:
    txt = "Merci Léa. Pouvez-vous me laisser votre numéro de téléphone pour le rappel ?"
    assert quick_replies(txt, needs_clarification=True) == []
    assert quick_replies("Sous quel nom je note votre rendez-vous ?") == []


def test_confirmation_ne_propose_pas_de_creneau() -> None:
    txt = (
        "C'est réservé : Brushing, samedi 31/10 à 10h. Un acompte garantit le créneau. "
        "Sous quel nom je note votre rendez-vous ?"
    )
    assert quick_replies(txt) == []


def test_jour_et_oui_non() -> None:
    assert quick_replies("Pour quel jour vous arrange ?") == ["Aujourd'hui", "Demain", "Ce samedi"]
    assert quick_replies("Je vous réserve ce créneau ?") == ["Oui", "Non"]
    assert quick_replies("Bonne journée !") == []
