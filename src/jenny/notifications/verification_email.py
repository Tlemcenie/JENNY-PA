"""Email de confirmation de compte (code à 6 chiffres), brandé Jenny.

Construit un :class:`EmailMessage` (texte + HTML) avec l'identité visuelle de
Jenny : dégradé corail, logo « J », et le code affiché en grandes cases. Le
HTML est volontairement écrit en tables + styles inline pour un rendu fiable
dans tous les clients mail (Gmail, Apple Mail, Outlook…).
"""

from __future__ import annotations

from html import escape

from jenny.notifications.email_sender import EmailMessage

# Palette Jenny (identique aux tokens du front).
_CORAL = "#FF7F6A"
_CORAL_DARK = "#E5674F"
_CORAL_LIGHT = "#FCBFB7"
_CORAL_TINT = "#FFF1EE"
_TEXT = "#1A1D26"
_TEXT_SECONDARY = "#6B7280"
_BG = "#FAFAFA"
_DIVIDER = "#E9EBEF"

_FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "Helvetica, Arial, sans-serif"
)


def _digit_boxes(code: str) -> str:
    cells = "".join(
        f'<td style="padding:0 5px;">'
        f'<div style="width:46px;height:58px;line-height:58px;text-align:center;'
        f"font-family:{_FONT};font-size:28px;font-weight:700;color:{_CORAL_DARK};"
        f"background:{_CORAL_TINT};border:1px solid {_CORAL_LIGHT};"
        f'border-radius:14px;">{escape(d)}</div>'
        f"</td>"
        for d in code
    )
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" '
        f'style="margin:0 auto;"><tr>{cells}</tr></table>'
    )


def build_verification_email(
    *,
    to: str,
    code: str,
    full_name: str | None = None,
    ttl_minutes: int = 15,
    app_name: str = "Jenny",
) -> EmailMessage:
    """Construit l'email de confirmation (texte + HTML brandé)."""
    greeting_name = (full_name or "").strip().split(" ")[0] if full_name else ""
    hello = f"Bonjour {escape(greeting_name)} 👋" if greeting_name else "Bonjour 👋"

    subject = f"Votre code de confirmation {app_name} — {code}"

    body_text = (
        f"{('Bonjour ' + greeting_name) if greeting_name else 'Bonjour'},\n\n"
        f"Bienvenue chez {app_name} ! Pour activer votre compte, saisissez ce code "
        f"de confirmation :\n\n"
        f"    Code : {code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes.\n\n"
        f"Vous n'avez pas créé de compte {app_name} ? Ignorez simplement cet email.\n\n"
        f"— L'équipe {app_name}"
    )

    body_html = f"""\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light only">
<title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#FFFFFF;border-radius:22px;overflow:hidden;box-shadow:0 8px 30px rgba(26,29,38,0.08);">
        <!-- Header brandé -->
        <tr>
          <td style="background:{_CORAL};background-image:linear-gradient(135deg,{_CORAL} 0%,{_CORAL_DARK} 100%);padding:34px 32px;text-align:center;">
            <table role="presentation" align="center" cellpadding="0" cellspacing="0" style="margin:0 auto;">
              <tr>
                <td style="vertical-align:middle;padding-right:12px;">
                  <div style="width:46px;height:46px;background:#FFFFFF;border-radius:14px;text-align:center;line-height:46px;font-family:{_FONT};font-size:24px;font-weight:800;color:{_CORAL_DARK};">J</div>
                </td>
                <td style="vertical-align:middle;">
                  <span style="font-family:{_FONT};font-size:24px;font-weight:700;color:#FFFFFF;letter-spacing:-0.3px;">{escape(app_name)}</span>
                </td>
              </tr>
            </table>
            <p style="margin:18px 0 0;font-family:{_FONT};font-size:14px;color:rgba(255,255,255,0.82);">Votre assistant IA pour vos clients</p>
          </td>
        </tr>
        <!-- Corps -->
        <tr>
          <td style="padding:36px 32px 28px;">
            <p style="margin:0 0 6px;font-family:{_FONT};font-size:15px;color:{_TEXT_SECONDARY};">{hello}</p>
            <h1 style="margin:0 0 14px;font-family:{_FONT};font-size:22px;line-height:1.3;font-weight:700;color:{_TEXT};">Confirmez votre adresse email</h1>
            <p style="margin:0 0 26px;font-family:{_FONT};font-size:15px;line-height:1.6;color:{_TEXT_SECONDARY};">Bienvenue chez {escape(app_name)} ! Saisissez ce code pour activer votre compte&nbsp;:</p>
            {_digit_boxes(code)}
            <p style="margin:24px 0 0;font-family:{_FONT};font-size:13px;color:{_TEXT_SECONDARY};text-align:center;">⏱️ Ce code expire dans <strong style="color:{_TEXT};">{ttl_minutes} minutes</strong>.</p>
          </td>
        </tr>
        <!-- Séparateur + note sécurité -->
        <tr>
          <td style="padding:0 32px 30px;">
            <div style="height:1px;background:{_DIVIDER};margin:0 0 18px;"></div>
            <p style="margin:0;font-family:{_FONT};font-size:13px;line-height:1.6;color:{_TEXT_SECONDARY};">Vous n'avez pas créé de compte {escape(app_name)} ? Vous pouvez ignorer cet email en toute sécurité, aucun compte ne sera activé.</p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:{_BG};padding:22px 32px;text-align:center;">
            <p style="margin:0;font-family:{_FONT};font-size:12px;color:{_TEXT_SECONDARY};">Envoyé avec ❤️ par {escape(app_name)}</p>
            <p style="margin:6px 0 0;font-family:{_FONT};font-size:11px;color:#9AA1AD;">WhatsApp · Instagram · Email · Twitter</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

    return EmailMessage(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
