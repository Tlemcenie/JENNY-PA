#!/usr/bin/env python3
"""teste les connecteurs."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# ajoute les chemins
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jenny.core.config import get_settings
from jenny.core.logging import setup_logging

setup_logging()

# couleurs terminal


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def success(msg: str) -> None:
    print(f"{Colors.GREEN}✅{Colors.RESET} {msg}")


def error(msg: str) -> None:
    print(f"{Colors.RED}❌{Colors.RESET} {msg}")


def info(msg: str) -> None:
    print(f"{Colors.BLUE}ℹ️{Colors.RESET} {msg}")


def warning(msg: str) -> None:
    print(f"{Colors.YELLOW}⚠️{Colors.RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'─' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'─' * 60}{Colors.RESET}\n")


# checks


def check_env() -> None:
    """affiche les vars d'env."""
    settings = get_settings()

    section("Configuration Chargée")

    # LLM
    info(f"LLM Provider: {settings.llm_provider}")
    if settings.llm_provider == "groq" and settings.groq_api_key:
        success(f"Groq API Key: {settings.groq_api_key[:20]}...")
    elif settings.llm_provider == "openai" and settings.openai_api_key:
        success(f"OpenAI API Key: {settings.openai_api_key[:20]}...")
    else:
        warning(f"LLM ({settings.llm_provider}) : pas de clé trouvée")

    # Connecteurs
    connectors = {
        "WhatsApp": (
            settings.whatsapp_phone_number_id,
            settings.whatsapp_access_token,
        ),
        "Instagram": (
            settings.instagram_page_id,
            settings.instagram_access_token,
        ),
        "Twilio": (
            settings.twilio_account_sid,
            settings.twilio_phone_number,
        ),
        "Email SMTP": (settings.smtp_host, settings.smtp_username),
        "Email IMAP": (settings.imap_host, settings.imap_user),
        "Stripe": (settings.stripe_secret_key,),
        "PayPal": (settings.paypal_client_id,),
        "Twitter": (settings.twitter_bearer_token,),
        "Google Calendar": (settings.google_service_account_json,),
    }

    for connector_name, values in connectors.items():
        configured = all(v for v in values)
        if configured:
            success(f"{connector_name}: ✓ Configuré")
        else:
            warning(f"{connector_name}: manque une clé")


async def check_whatsapp_health() -> None:
    """vérifie whatsapp."""
    settings = get_settings()
    if not settings.whatsapp_access_token:
        error("WhatsApp: TOKEN MANQUANT")
        return

    success("WhatsApp: Configuration présente")
    info("Pour tester le webhook, lancer :")
    print("  curl -X POST http://localhost:8000/webhooks/whatsapp \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"entry\": [{\"changes\": [{\"value\": {\"messages\": []}}]}]}'")


async def check_instagram_health() -> None:
    """vérifie instagram."""
    settings = get_settings()
    if not settings.instagram_access_token:
        error("Instagram: TOKEN MANQUANT")
        return

    success("Instagram: Configuration présente")
    info("Pour tester le webhook, lancer :")
    print("  curl -X POST http://localhost:8000/webhooks/instagram \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"entry\": [{\"messaging\": []}]}'")



async def test_webhook_simulation(channel: str) -> None:
    """simule un webhook."""
    section(f"Simulation Webhook — {channel.upper()}")

    if channel == "whatsapp":
        from jenny.connectors.whatsapp.schema import WhatsAppWebhookPayload

        payload_data = {
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "33612345678",
                                        "id": "msg_123",
                                        "type": "text",
                                        "text": {"body": "Bonjour!"},
                                        "timestamp": "1234567890",
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": "33612345678",
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ],
                }
            ]
        }

        try:
            payload = WhatsAppWebhookPayload.model_validate(payload_data)
            success(f"Payload valide ✓")
            info(f"Nombre de messages: {len(payload.entry[0].changes[0].value.messages)}")
        except Exception as e:
            error(f"Erreur validation: {e}")

    elif channel == "instagram":
        from jenny.connectors.instagram.schema import IGWebhookPayload

        payload_data = {
            "entry": [
                {
                    "id": "1",
                    "messaging": [
                        {
                            "sender": {"id": "user_123"},
                            "recipient": {"id": "page_123"},
                            "message": {"mid": "msg_456", "text": "Hello!"},
                            "timestamp": 1234567890,
                        }
                    ],
                }
            ]
        }

        try:
            payload = IGWebhookPayload.model_validate(payload_data)
            success(f"Payload valide ✓")
        except Exception as e:
            error(f"Erreur validation: {e}")

    else:
        warning(f"Canal {channel} : simulation non implémentée")


def show_usage() -> None:
    """affiche l'aide."""
    print(__doc__)


# main


async def main() -> None:
    """lance les tests."""
    import argparse

    parser = argparse.ArgumentParser(description="Test des connecteurs Jenny")
    parser.add_argument(
        "--env-check",
        action="store_true",
        help="Vérifier les variables d'env chargées",
    )
    parser.add_argument(
        "--channel",
        help="Tester un connecteur spécifique (whatsapp, instagram, etc)",
    )
    parser.add_argument(
        "--webhook",
        help="Simuler un webhook",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mode verbose",
    )

    args = parser.parse_args()

    section("🚀 Jenny — Test des Connecteurs")

    if args.env_check or not any([args.channel, args.webhook]):
        check_env()

    if args.channel == "whatsapp":
        await check_whatsapp_health()

    elif args.channel == "instagram":
        await check_instagram_health()

    elif args.webhook:
        await test_webhook_simulation(args.webhook)

    section("✅ Test Terminé")
    
    info("Pour lancer l'API : make api")
    info("Pour lancer les tests : make test")
    info("Pour voir les logs : tail -f logs/jenny.log")


if __name__ == "__main__":
    asyncio.run(main())
