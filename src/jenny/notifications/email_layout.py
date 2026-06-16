"""Gabarit d'email premium — DA « Jenny » (nuit profonde + corail + serif).

Identité visuelle identique au site : fond nuit ``#0E0B14``, carte sombre,
accents corail, titres en serif éditorial (Instrument Serif, repli Georgia),
libellés mono. 100 % tables + styles inline → rendu fiable Gmail/Apple Mail/
Outlook ; aucune image externe (le logo est un monogramme CSS, jamais bloqué).

Point d'entrée : :func:`render_email`. Helpers : :func:`code_boxes`,
:func:`button`.
"""

from __future__ import annotations

from html import escape

# ── Palette (tokens du front) ──
NIGHT = "#0E0B14"
CARD = "#17121F"
CARD_SOFT = "#1F1A29"
CORAL = "#FF7F6A"
CORAL_DARK = "#E5674F"
CORAL_TINT = "#2A1C20"
CREAM = "#F4F1ED"
MUTED = "#A39DB0"
FAINT = "#6E687A"
BORDER = "#2A2433"

# Serif éditorial (Apple Mail charge la web font ; ailleurs → Georgia, élégant).
SERIF = "'Instrument Serif', Georgia, 'Times New Roman', serif"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "'SF Mono', ui-monospace, Menlo, Consolas, monospace"

# La mascotte Jenny est embarquée DANS l'email (pièce jointe inline, Content-ID) —
# pas un lien externe (que les clients mail bloquent). EmailSender l'attache
# automatiquement dès que le HTML référence `cid:jenny-mascot`.
MASCOT_CID = "jenny-mascot"


def code_boxes(code: str) -> str:
    """Le code de confirmation en grandes cases corail (centré)."""
    cells = "".join(
        f'<td style="padding:0 4px;">'
        f'<div style="width:42px;height:54px;line-height:54px;text-align:center;'
        f"font-family:{MONO};font-size:26px;font-weight:700;color:{CORAL};"
        f"background:{CORAL_TINT};border:1px solid {CORAL_DARK};border-radius:12px;\">"
        f"{escape(d)}</div></td>"
        for d in code
    )
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" '
        f'style="margin:0 auto;"><tr>{cells}</tr></table>'
    )


def button(label: str, url: str) -> str:
    """Bouton corail « bulletproof » (table) centré."""
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" style="margin:0 auto;">'
        f'<tr><td style="border-radius:999px;background:{CORAL};">'
        f'<a href="{escape(url, quote=True)}" target="_blank" '
        f'style="display:inline-block;padding:14px 30px;font-family:{SANS};font-size:15px;'
        f'font-weight:600;color:#1A0A08;text-decoration:none;border-radius:999px;">'
        f"{escape(label)}</a></td></tr></table>"
    )


def render_email(
    *,
    preheader: str,
    eyebrow: str,
    heading: str,
    accent: str = "",
    paragraphs: list[str] | None = None,
    content_html: str = "",
    note: str | None = None,
    app_name: str = "Jenny",
) -> str:
    """Document HTML complet, DA Jenny.

    - ``eyebrow`` : petit libellé mono au-dessus du titre.
    - ``heading`` + ``accent`` : titre serif ; ``accent`` rendu en italique corail.
    - ``paragraphs`` : texte courant (échappé ici).
    - ``content_html`` : bloc déjà mis en forme (cases de code, bouton…).
    - ``note`` : petite note de pied (sécurité / ignorer si non concerné).
    """
    paras = "".join(
        f'<p style="margin:0 0 16px;font-family:{SANS};font-size:15px;line-height:1.62;color:{MUTED};">{p}</p>'
        for p in (paragraphs or [])
    )
    accent_html = (
        f' <span style="font-style:italic;color:{CORAL};">{escape(accent)}</span>' if accent else ""
    )
    note_block = (
        f'<tr><td style="padding:0 36px 30px;">'
        f'<div style="height:1px;background:{BORDER};margin:0 0 18px;"></div>'
        f'<p style="margin:0;font-family:{SANS};font-size:12.5px;line-height:1.6;color:{FAINT};">{note}</p>'
        f"</td></tr>"
        if note
        else ""
    )

    return f"""\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark light">
<meta name="supported-color-schemes" content="dark light">
<title>{escape(app_name)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');
  body {{ margin:0; padding:0; }}
  a {{ color:{CORAL}; }}
</style>
</head>
<body style="margin:0;padding:0;background:{NIGHT};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{NIGHT};font-size:1px;line-height:1px;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NIGHT};padding:36px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:{CARD};border:1px solid {BORDER};border-radius:24px;overflow:hidden;">
        <!-- Header : mascotte Jenny (inline CID) + wordmark serif -->
        <tr>
          <td style="padding:38px 36px 4px;text-align:center;">
            <table role="presentation" align="center" cellpadding="0" cellspacing="0" style="margin:0 auto;">
              <tr>
                <td width="100" height="100" style="width:100px;height:100px;background:{CORAL_TINT};border:1px solid {BORDER};border-radius:50%;text-align:center;vertical-align:middle;">
                  <img src="cid:{MASCOT_CID}" width="72" height="72" alt="{escape(app_name)}" style="display:inline-block;border:0;outline:none;text-decoration:none;vertical-align:middle;">
                </td>
              </tr>
            </table>
            <div style="font-family:{SERIF};font-size:32px;color:{CREAM};letter-spacing:-0.5px;margin:16px 0 0;">{escape(app_name)}</div>
            <div style="font-family:{SANS};font-size:13px;color:{MUTED};margin:4px 0 0;">Votre assistante, jamais en pause.</div>
          </td>
        </tr>
        <!-- Corps -->
        <tr>
          <td style="padding:22px 36px 8px;">
            <div style="font-family:{MONO};font-size:11px;letter-spacing:3px;text-transform:uppercase;color:{CORAL};margin:0 0 14px;">— {escape(eyebrow)} —</div>
            <h1 style="margin:0 0 18px;font-family:{SERIF};font-size:34px;line-height:1.12;font-weight:400;color:{CREAM};">{escape(heading)}{accent_html}</h1>
            {paras}
          </td>
        </tr>
        <tr><td style="padding:6px 36px 30px;">{content_html}</td></tr>
        {note_block}
        <!-- Footer -->
        <tr>
          <td style="background:{CARD_SOFT};padding:22px 36px;text-align:center;border-top:1px solid {BORDER};">
            <p style="margin:0;font-family:{MONO};font-size:11px;letter-spacing:1px;color:{FAINT};">WHATSAPP · INSTAGRAM · EMAIL</p>
            <p style="margin:8px 0 0;font-family:{SANS};font-size:11px;color:{FAINT};">© 2026 {escape(app_name)} — Hébergé en France · RGPD</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""
