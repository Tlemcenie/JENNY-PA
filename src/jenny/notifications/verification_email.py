"""Emails de compte (confirmation, réinitialisation) — DA « Jenny ».

S'appuie sur le gabarit premium partagé :mod:`jenny.notifications.email_layout`
(fond nuit, serif corail, cases de code). Texte brut + HTML pour un rendu fiable
partout.
"""

from __future__ import annotations

from jenny.notifications.email_layout import code_boxes, render_email
from jenny.notifications.email_sender import EmailMessage


def _greeting(full_name: str | None) -> str:
    first = (full_name or "").strip().split(" ")[0] if full_name else ""
    return f"Bonjour {first}," if first else "Bonjour,"


def build_verification_email(
    *,
    to: str,
    code: str,
    full_name: str | None = None,
    ttl_minutes: int = 15,
    app_name: str = "Jenny",
) -> EmailMessage:
    """Email de confirmation de compte (code à 6 chiffres), brandé Jenny."""
    hello = _greeting(full_name)
    subject = f"Votre code de confirmation {app_name} — {code}"

    body_text = (
        f"{hello}\n\n"
        f"Bienvenue chez {app_name} ! Pour activer votre compte, saisissez ce code :\n\n"
        f"    {code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes.\n\n"
        f"Vous n'avez pas créé de compte {app_name} ? Ignorez cet email.\n\n"
        f"— L'équipe {app_name}"
    )

    expiry_note = (
        f'<p style="margin:18px 0 0;font-family:-apple-system,Arial,sans-serif;'
        f'font-size:13px;color:#A39DB0;text-align:center;">'
        f"Ce code expire dans <strong style=\"color:#F4F1ED;\">{ttl_minutes} minutes</strong>.</p>"
    )

    body_html = render_email(
        preheader=f"Votre code de confirmation : {code}",
        eyebrow="confirmation",
        heading="Confirmez votre",
        accent="adresse email.",
        paragraphs=[
            f"{hello[:-1]} 👋 — bienvenue chez <b style=\"color:#F4F1ED;\">{app_name}</b>.",
            "Saisissez ce code pour activer votre compte :",
        ],
        content_html=code_boxes(code) + expiry_note,
        note=(
            f"Vous n'avez pas créé de compte {app_name} ? Vous pouvez ignorer cet email "
            "en toute sécurité — aucun compte ne sera activé."
        ),
        app_name=app_name,
    )

    return EmailMessage(to=to, subject=subject, body_text=body_text, body_html=body_html)


def build_reset_email(
    *,
    to: str,
    code: str,
    full_name: str | None = None,
    ttl_minutes: int = 15,
    app_name: str = "Jenny",
) -> EmailMessage:
    """Email de réinitialisation de mot de passe (code), brandé Jenny."""
    hello = _greeting(full_name)
    subject = f"Réinitialisation de votre mot de passe {app_name} — {code}"

    body_text = (
        f"{hello}\n\n"
        f"Vous avez demandé à réinitialiser votre mot de passe {app_name}. "
        f"Saisissez ce code pour continuer :\n\n"
        f"    {code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes.\n\n"
        f"Vous n'êtes pas à l'origine de cette demande ? Ignorez cet email, "
        f"votre mot de passe reste inchangé.\n\n"
        f"— L'équipe {app_name}"
    )

    expiry_note = (
        f'<p style="margin:18px 0 0;font-family:-apple-system,Arial,sans-serif;'
        f'font-size:13px;color:#A39DB0;text-align:center;">'
        f"Ce code expire dans <strong style=\"color:#F4F1ED;\">{ttl_minutes} minutes</strong>.</p>"
    )

    body_html = render_email(
        preheader=f"Votre code de réinitialisation : {code}",
        eyebrow="sécurité",
        heading="Réinitialisez votre",
        accent="mot de passe.",
        paragraphs=[
            f"{hello} Vous avez demandé à réinitialiser votre mot de passe.",
            "Saisissez ce code pour définir un nouveau mot de passe :",
        ],
        content_html=code_boxes(code) + expiry_note,
        note=(
            "Vous n'êtes pas à l'origine de cette demande ? Ignorez cet email : "
            "votre mot de passe reste inchangé."
        ),
        app_name=app_name,
    )

    return EmailMessage(to=to, subject=subject, body_text=body_text, body_html=body_html)
