"""Repérage des prestations."""

import time

from jenny.engine.catalog_match import ambiguous_heads, find_services

CAT = ["Coupe femme", "Coupe homme", "Brushing", "Coloration", "Balayage", "Soin profond", "Barbe"]


def test_exact_et_ordre_libre() -> None:
    assert find_services("une coupe femme svp", CAT) == ["Coupe femme"]
    assert find_services("coupe pour homme", CAT) == ["Coupe homme"]
    assert find_services("des coupes femmes", CAT) == ["Coupe femme"]


def test_synonymes_et_fautes() -> None:
    assert find_services("je veux faire une couleur", CAT) == ["Coloration"]
    assert find_services("un balyage", CAT) == ["Balayage"]
    assert find_services("brusing", CAT) == ["Brushing"]
    assert find_services("coupe pour mon garçon", CAT) == ["Coupe homme"]


def test_tete_unique() -> None:
    assert find_services("un soin", CAT) == ["Soin profond"]
    # coupe : deux choix, pas de pari
    assert find_services("une coupe", CAT) == []
    assert ambiguous_heads("une coupe", CAT) == ["Coupe femme", "Coupe homme"]


def test_plusieurs() -> None:
    assert find_services("coupe femme et balayage", CAT) == ["Coupe femme", "Balayage"]


def test_rien() -> None:
    assert find_services("bonjour, vous êtes ouverts ?", CAT) == []
    assert find_services("", CAT) == []


def test_lineaire() -> None:
    t = time.perf_counter()
    find_services("coupe " * 5000, CAT)
    assert time.perf_counter() - t < 0.2


async def test_moteur_demande_femme_ou_homme() -> None:
    """« une coupe » : Jenny demande laquelle."""
    from uuid import uuid4

    from jenny.engine.conversation_engine import EngineRequest
    from jenny.engine.factory import build_engine

    eng = build_engine()
    eng.response_generator = None
    req = EngineRequest(
        conversation_id=uuid4(),
        business_id=uuid4(),
        message_text="Je voudrais un rendez-vous pour une coupe demain à 10h",
        catalog_services=CAT,
    )
    await eng.process(req)
    state = await eng.state_manager.aget(req.conversation_id)
    assert not (state.slots.get("service") and state.slots["service"].filled)
    assert "coupe femme ou coupe homme" in (state.clarification_instruction or "")
