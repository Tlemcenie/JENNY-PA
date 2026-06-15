#!/usr/bin/env python3
"""🤖 Jenny — Chat interactif dans le terminal.

Lance une vraie conversation avec Jenny, avec :
- Détection d'intention (modèle LSTM multi-label)
- Extraction d'entités (modèle BiGRU NER)
- Routage vers les agents métier
- Réponses naturelles via LLM (Groq Llama 3.3 70B)
- Clarification quand Jenny n'est pas sûre

Usage :
    python chat.py
    PYTHONPATH=src:. python chat.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

# ── Rich pour le rendu terminal ──
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def main() -> None:
    if HAS_RICH:
        console = Console()
    else:
        console = None

    def cprint(msg: str, **kwargs) -> None:
        if console:
            console.print(msg, **kwargs)
        else:
            print(msg)

    # ── Banner ──
    if console:
        banner = Panel(
            "[bold magenta]🤖 JENNY AI[/bold magenta]\n"
            "[dim]Plateforme intelligente de gestion des messages clients[/dim]\n\n"
            "[cyan]Tapez vos messages comme un vrai client.[/cyan]\n"
            "[dim]Commandes : [bold]/quit[/bold] quitter · [bold]/debug[/bold] toggle debug · [bold]/reset[/bold] nouvelle conversation[/dim]",
            title="[bold white]Chat Interactif[/bold white]",
            border_style="magenta",
            width=80,
        )
        console.print(banner)
    else:
        print("=" * 60)
        print("🤖 JENNY AI — Chat Interactif")
        print("=" * 60)
        print("Tapez vos messages. /quit pour quitter.\n")

    # ── Charger les modèles ML ──
    cprint("\n⏳ Chargement des composants...", style="dim" if console else None)

    intent_predictor = None
    ner_predictor = None

    try:
        from ml.models.intent.predict import IntentPredictor
        intent_predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")
        cprint("  ✅ Intent model (14 intents, multi-label)", style="green" if console else None)
    except Exception as e:
        cprint(f"  ⚠️  Intent model indisponible : {e}", style="yellow" if console else None)

    try:
        from ml.models.ner.predict import NERPredictor
        ner_predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")
        cprint("  ✅ NER model (11 entités)", style="green" if console else None)
    except Exception as e:
        cprint(f"  ⚠️  NER model indisponible : {e}", style="yellow" if console else None)

    # ── LLM Provider (Groq) ──
    from jenny.llm.providers import GroqProvider
    from jenny.llm.prompts import PromptBuilder
    from jenny.engine.response_generator import ResponseGenerator

    groq_key = os.getenv("JENNY_GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    llm = GroqProvider(model="llama-3.3-70b-versatile", api_key=groq_key)
    prompt_builder = PromptBuilder(business_type="un salon de coiffure")
    response_generator = ResponseGenerator(llm_provider=llm, prompt_builder=prompt_builder)
    cprint(f"  ✅ LLM : {llm.model_name} (Groq)", style="green" if console else None)

    # ── Agents ──
    from jenny.agents.router import AgentRouter
    from jenny.agents.fallback_agent import FallbackAgent
    from jenny.agents.faq_agent import FAQAgent
    from jenny.agents.payment_agent import PaymentAgent
    from jenny.agents.quote_agent import QuoteAgent
    from jenny.agents.planning_agent import PlanningAgent
    from jenny.agents.action_agent import ActionAgent
    from jenny.integrations.google_calendar import GoogleCalendarService
    from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
    from jenny.engine.state_manager import StateManager

    router = AgentRouter()
    calendar = GoogleCalendarService()

    router.register("fallback", FallbackAgent())
    router.register("faq", FAQAgent())
    router.register("payment", PaymentAgent())
    router.register("quote", QuoteAgent())
    router.register("planning", PlanningAgent(calendar_service=calendar))
    router.register("action", ActionAgent())

    state_manager = StateManager()
    cprint(f"  💾 State : {state_manager.backend}", style="cyan" if console else None)

    engine = ConversationEngine(
        state_manager=state_manager,
        intent_predictor=intent_predictor,
        ner_predictor=ner_predictor,
        agent_router=router,
        response_generator=response_generator,
    )

    cprint("\n✅ Jenny est prête ! Parlez-lui.\n", style="bold green" if console else None)

    # ── Boucle de conversation ──
    conversation_id = uuid4()
    business_id = uuid4()
    debug_mode = False

    async def process(text: str) -> dict:
        request = EngineRequest(
            conversation_id=conversation_id,
            business_id=business_id,
            message_text=text,
            channel="terminal",
        )
        response = await engine.process(request)
        return {
            "response": response.response_text,
            "intent": response.intent,
            "confidence": response.intent_confidence,
            "detected_intents": response.detected_intents or [],
            "is_multi_intent": response.is_multi_intent,
            "needs_clarification": response.needs_clarification,
            "entities": response.entities,
            "agent": response.agent_used,
            "action_result": response.action_result,
            "phase": response.conversation_phase,
            "requires_human": response.requires_human,
        }

    while True:
        try:
            if console:
                user_input = console.input("[bold cyan]Vous >[/bold cyan] ").strip()
            else:
                user_input = input("Vous > ").strip()
        except (KeyboardInterrupt, EOFError):
            cprint("\n👋 À bientôt !", style="magenta" if console else None)
            break

        if not user_input:
            continue

        if user_input.lower() == "/quit":
            cprint("👋 À bientôt !", style="magenta" if console else None)
            break

        if user_input.lower() == "/debug":
            debug_mode = not debug_mode
            cprint(f"🔧 Debug {'activé' if debug_mode else 'désactivé'}", style="yellow" if console else None)
            continue

        if user_input.lower() == "/reset":
            conversation_id = uuid4()
            cprint("🔄 Nouvelle conversation !", style="yellow" if console else None)
            continue

        # Traiter le message
        try:
            result = asyncio.run(process(user_input))
        except Exception as e:
            cprint(f"❌ Erreur : {e}", style="red" if console else None)
            import traceback
            traceback.print_exc()
            continue

        # ── Afficher le debug si activé ──
        if debug_mode and console:
            debug_table = Table(title="🔍 Debug", show_header=True, border_style="dim")
            debug_table.add_column("Champ", style="dim")
            debug_table.add_column("Valeur", style="cyan")

            intents_str = ", ".join(
                f"{d['intent']}({d['confidence']:.0%})"
                for d in result["detected_intents"]
            ) if result["detected_intents"] else "—"
            debug_table.add_row("Intent principal", f"{result['intent']} ({result['confidence']:.0%})")
            debug_table.add_row("Tous les intents", intents_str)
            debug_table.add_row("Multi-intent", "✅" if result["is_multi_intent"] else "❌")
            debug_table.add_row("Clarification", "🤔 Oui" if result["needs_clarification"] else "❌ Non")
            debug_table.add_row("Agent", result["agent"] or "—")
            debug_table.add_row("Phase", result["phase"])

            if result["entities"]:
                entities_str = ", ".join(f"{k}={v}" for k, v in result["entities"].items())
                debug_table.add_row("Entités NER", entities_str)
            else:
                debug_table.add_row("Entités NER", "—")

            if result["action_result"]:
                ar = result["action_result"]
                debug_table.add_row("Action", str(ar.get("type", ar.get("message", "—")))[:60])

            if result["requires_human"]:
                debug_table.add_row("🚨 Escalade", "Oui — transfert humain")

            console.print(debug_table)
            console.print()

        elif debug_mode:
            print(f"  [DEBUG] intent={result['intent']}({result['confidence']:.0%}) "
                  f"agent={result['agent']} entities={result['entities']}")

        # ── Afficher la réponse de Jenny ──
        if console:
            jenny_panel = Panel(
                result["response"],
                title="[bold magenta]🤖 Jenny[/bold magenta]",
                border_style="magenta",
                width=78,
                padding=(0, 2),
            )
            console.print(jenny_panel)
        else:
            print(f"\n🤖 Jenny : {result['response']}\n")


if __name__ == "__main__":
    main()
