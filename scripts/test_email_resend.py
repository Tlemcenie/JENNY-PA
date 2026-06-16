"""Test d'envoi d'email réel via le relais SMTP Resend (config .env).

Utilise EXACTEMENT le même chemin que les emails de Jenny (EmailSender → SMTP),
donc si ce test passe, la confirmation de compte et le reset de mot de passe
partiront aussi. Aucune lib spécifique : Resend = relais SMTP.

Usage :
    # 1. Colle ta clé dans .env :  JENNY_SMTP_PASSWORD=re_xxx
    # 2. Lance :
    .venv/bin/python scripts/test_email_resend.py [destinataire@example.com]

Note Resend : tant que ton domaine n'est pas vérifié, l'expéditeur DOIT être
`onboarding@resend.dev` et le destinataire DOIT être l'email de TON compte Resend.
"""

from __future__ import annotations

import asyncio
import sys

from jenny.core.config import get_settings
from jenny.notifications.email_sender import EmailMessage, EmailSender


async def main() -> int:
    settings = get_settings()
    to = sys.argv[1] if len(sys.argv) > 1 else "yassine.benzenine49@hotmail.fr"

    print("── Config SMTP effective ──")
    print(f"  host     : {settings.smtp_host}:{settings.smtp_port}")
    print(f"  username : {settings.smtp_username or '(vide)'}")
    print(f"  from     : {settings.smtp_from_email or '(vide)'}")
    print(f"  password : {'défini ✅' if settings.smtp_password else 'VIDE ❌'}")
    print(f"  → destinataire : {to}\n")

    if not settings.smtp_password:
        print("⚠️  JENNY_SMTP_PASSWORD est vide dans .env → l'email sera écrit dans")
        print("    var/emails/ (backend fichier), PAS envoyé. Colle ta clé Resend d'abord.")

    sender = EmailSender()
    backend = sender._resolve_backend()  # noqa: SLF001 - diagnostic
    print(f"Backend résolu : {backend}\n")

    msg = EmailMessage(
        to=to,
        subject="Jenny — test d'envoi via Resend ✅",
        body_text="Si tu lis ceci dans ta boîte, l'envoi d'emails de Jenny fonctionne.",
        body_html=(
            "<div style='font-family:sans-serif'>"
            "<h2>Jenny — test d'envoi</h2>"
            "<p>Si tu lis ceci dans ta boîte, l'envoi d'emails "
            "(confirmation, reset de mot de passe, RDV) <b>fonctionne</b> 🎉</p>"
            "</div>"
        ),
    )
    ok = await sender.send(msg)
    print(f"\nRésultat : {'ENVOYÉ ✅' if ok else 'ÉCHEC ❌'} (backend={backend})")
    if backend == "file":
        print("  (mode fichier : voir var/emails/ — l'email n'est pas vraiment parti)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
