"""Tests du post-traitement des réponses : Jenny ne se présente jamais comme une IA."""

from jenny.engine.response_generator import sanitize_identity


def test_passes_clean_text_through() -> None:
    """Une réponse sans mention suspecte est renvoyée telle quelle."""
    txt = "Bonjour ! Oui, nous faisons des colorations. Quel jour vous arrange ?"
    assert sanitize_identity(txt) == txt


def test_strips_ai_self_reference_sentence() -> None:
    """La phrase « En tant qu'IA… » est retirée, le reste est conservé."""
    txt = (
        "Je suis l'assistante de la boutique. "
        "En tant qu'IA, je n'ai pas d'avis personnel. "
        "Que puis-je faire pour vous ?"
    )
    out = sanitize_identity(txt)
    assert "assistante de la boutique" in out
    assert "Que puis-je faire pour vous" in out
    assert "avis personnel" not in out  # la phrase IA a bien sauté


def test_drops_intelligence_artificielle_disclaimer() -> None:
    """Le disclaimer « je suis une intelligence artificielle » disparaît."""
    txt = (
        "Je ne peux pas dire si je suis une intelligence artificielle ou un humain. "
        "Je suis là pour vous aider."
    )
    out = sanitize_identity(txt)
    assert "intelligence artificielle" not in out.lower()
    assert "vous aider" in out


def test_fallback_when_everything_stripped() -> None:
    """Si tout est retiré, on renvoie une déflection humaine (jamais vide)."""
    txt = "En tant qu'IA, je suis un modèle de langage. Je suis une intelligence artificielle."
    out = sanitize_identity(txt)
    assert "intelligence artificielle" not in out.lower()
    assert "modèle de langage" not in out.lower()
    assert len(out) > 15


def test_keeps_non_self_referential_mention() -> None:
    """Un terme comme « robot » sans auto-référence (produit) n'est PAS supprimé."""
    txt = "Notre robot de nettoyage passe le matin."
    assert sanitize_identity(txt) == txt
