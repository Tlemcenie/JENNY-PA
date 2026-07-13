"""Tests du post-traitement des réponses : Jenny ne se présente jamais comme une IA."""

from jenny.engine.response_generator import (
    cap_paragraphs,
    polish_response,
    sanitize_identity,
    strip_dialogue_scaffold,
    strip_false_booking_confirmation,
    strip_filler_phrases,
    strip_inline_address,
    strip_letter_format,
    strip_model_artifacts,
    trim_filler_closing,
    trim_trailing_deflection,
)


def test_strips_hallucinated_booking_confirmation() -> None:
    # Sans reservation aboutie, une confirmation avec jour/heure est retiree.
    out = strip_false_booking_confirmation(
        "On se voit mardi à 16h35 pour votre coupe homme.", booking_confirmed=False
    )
    assert "16h35" not in out and "mardi" not in out
    assert len(out) > 15  # repli sur une relance sure, jamais vide


def test_keeps_confirmation_when_booking_really_succeeded() -> None:
    txt = "C'est noté, on se voit jeudi à 10h !"
    assert strip_false_booking_confirmation(txt, booking_confirmed=True) == txt


def test_does_not_strip_a_booking_question() -> None:
    # Une QUESTION de RDV n'est pas une confirmation : elle doit rester.
    txt = "Une coupe femme coûte 39€. Vous voulez un rendez-vous demain ?"
    assert strip_false_booking_confirmation(txt, booking_confirmed=False) == txt


def test_strips_conflict_false_reception() -> None:
    out = strip_false_booking_confirmation("Je vous reçois à 10h ce jeudi.", booking_confirmed=False)
    assert "10h" not in out


def test_strips_leaked_dialogue_scaffold() -> None:
    out = strip_dialogue_scaffold("Client : ... Jenny : Bonjour, je peux vous aider ?")
    assert out == "Bonjour, je peux vous aider ?"


def test_strips_filler_phrase_mid_message() -> None:
    out = strip_filler_phrases("On est ouverts samedi. N'hésitez pas si besoin. À très vite.")
    assert "hésitez" not in out.lower()
    assert "ouverts samedi" in out and "très vite" in out


def test_trims_deflection_after_grounded_answer() -> None:
    # Réponse fondée + déflexion collée → on retire la déflexion (bruit).
    assert (
        trim_trailing_deflection(
            "Une coupe femme coûte 39€. Je vérifie tout de suite et je reviens vers vous !",
            grounded=True,
        )
        == "Une coupe femme coûte 39€."
    )


def test_keeps_deflection_when_sole_content_or_ungrounded() -> None:
    sole = "Je vérifie ça et je reviens vers vous."
    assert trim_trailing_deflection(sole, grounded=True) == sole  # seule phrase
    ung = "Le prix du permis moto ? Je vérifie et reviens vers vous."
    assert trim_trailing_deflection(ung, grounded=False) == ung  # non fondé


def test_strips_inline_madame_monsieur() -> None:
    out = strip_inline_address("Je vous remercie, madame ou monsieur, nous fermons à 19h.")
    assert "madame" not in out.lower() and "monsieur" not in out.lower()
    assert "fermons à 19h" in out


def test_caps_to_two_paragraphs_keeping_question() -> None:
    txt = "Bloc un utile.\n\nBloc deux détail.\n\nBloc trois. Vous voulez réserver ?"
    out = cap_paragraphs(txt)
    assert out.count("\n\n") == 2
    assert out.rstrip().endswith("Vous voulez réserver ?")
    assert "Bloc trois" not in out


def test_polish_trims_deflection_only_when_grounded() -> None:
    """polish_response enlève la déflexion collée à une réponse FONDÉE, la garde sinon."""
    grounded = polish_response(
        "Une coupe homme coûte 25€. Je vérifie et je reviens vers vous !",
        already_spoke=True,
        grounded=True,
    )
    assert "25" in grounded
    assert "vérifie" not in grounded.lower()

    ungrounded = polish_response(
        "Je vérifie ça et je reviens vers vous tout de suite.",
        already_spoke=True,
        grounded=False,
    )
    assert "vérifie" in ungrounded.lower()  # seule info → jamais retirée


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
    raw = "Super ! Je保留未翻译  <|im_start|>user 好的，请继续."  # noqa: RUF001 - CJK volontaire (test glitch qwen)
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
