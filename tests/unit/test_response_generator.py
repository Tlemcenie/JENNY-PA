"""Tests du post-traitement des réponses : Jenny ne se présente jamais comme une IA."""

from jenny.engine.response_generator import (
    polish_response,
    sanitize_identity,
    strip_letter_format,
    strip_model_artifacts,
    trim_filler_closing,
)


def test_trims_empty_closing_filler() -> None:
    assert (
        trim_filler_closing(
            "Une coupe femme coûte 39€. N'hésitez pas si vous avez d'autres questions !"
        )
        == "Une coupe femme coûte 39€."
    )
    assert (
        trim_filler_closing("On fait le balayage à 80€. Je reste à votre disposition.")
        == "On fait le balayage à 80€."
    )


def test_keeps_real_question_closing() -> None:
    txt = "Oui, on est ouverts samedi ! Vous voulez que je vous réserve un moment ?"
    assert trim_filler_closing(txt) == txt


def test_keeps_single_short_closing() -> None:
    assert trim_filler_closing("Avec plaisir, à très vite !") == "Avec plaisir, à très vite !"


def test_does_not_trim_deflection() -> None:
    # La déflexion sert à la détection de lacune → ne jamais la retirer.
    txt = "Je vérifie ça et je reviens vers vous tout de suite."
    assert trim_filler_closing(txt) == txt


def test_strips_chat_template_token_and_cjk() -> None:
    """Fuite de gabarit ChatML + texte chinois (glitch qwen) → tout est retiré."""
    raw = "Super ! Je保留未翻译  <|im_start|>user 好的，请继续."
    out = strip_model_artifacts(raw)
    assert "<|" not in out
    assert "保" not in out and "好" not in out
    assert out.startswith("Super")


def test_model_artifacts_leave_clean_text_untouched() -> None:
    txt = "On se voit jeudi Camille ! À très vite 😊"
    assert strip_model_artifacts(txt) == txt


def test_polish_strips_model_artifacts_end_to_end() -> None:
    raw = "Votre RDV est confirmé. <|im_end|>\n好的"
    out = polish_response(raw, already_spoke=True)
    assert "<|" not in out and "好" not in out
    assert "confirmé" in out


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


def test_strips_letter_opening_and_signature() -> None:
    """Le format courrier (formule d'appel + signature) est retiré : c'est un message."""
    txt = (
        "Chère cliente,\n\n"
        "Le shampoing et le brushing sont inclus dans toutes nos coupes.\n\n"
        "Bien cordialement,\nJenny"
    )
    out = strip_letter_format(txt)
    assert out.startswith("Le shampoing")
    assert "Chère cliente" not in out
    assert "cordialement" not in out.lower()
    assert out.rstrip().endswith("coupes.")


def test_letter_format_leaves_normal_chat_untouched() -> None:
    """Un message de chat normal (« À très vite ! ») n'est pas tronqué."""
    txt = "Avec plaisir, à très vite ! 😊"
    assert strip_letter_format(txt) == txt


def test_polish_strips_letter_format_end_to_end() -> None:
    """polish_response enchaîne le nettoyage : plus de formule d'appel ni de signature."""
    txt = "Madame,\n\nNous sommes ouverts jusqu'à 19h.\n\nCordialement,\nJenny"
    out = polish_response(txt, already_spoke=True)
    assert "Madame" not in out
    assert "ordialement" not in out
    assert "ouverts jusqu'à 19h" in out
