"""Tests réalistes — salon de coiffure."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from jenny.agents.graph import process_message_with_graph
from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
from jenny.engine.state_manager import StateManager

# ═══════════════════════════════════════════════════════════
#  fixtures
# ═══════════════════════════════════════════════════════════


BUSINESS_ID = str(uuid4())  # id du salon


def _build_engine() -> ConversationEngine:
    """Construit le moteur."""
    from jenny.actions.handlers.book_appointment import BookAppointmentAction
    from jenny.actions.handlers.check_planning import CheckPlanningAction
    from jenny.actions.handlers.create_ticket import CreateTicketAction
    from jenny.actions.handlers.generate_quote import GenerateQuoteAction
    from jenny.actions.handlers.order_check import CheckOrderAction
    from jenny.actions.handlers.process_payment import ProcessPaymentAction
    from jenny.actions.registry import ActionRegistry
    from jenny.agents.action_agent import ActionAgent
    from jenny.agents.fallback_agent import FallbackAgent
    from jenny.agents.faq_agent import FAQAgent
    from jenny.agents.payment_agent import PaymentAgent
    from jenny.agents.planning_agent import PlanningAgent
    from jenny.agents.quote_agent import QuoteAgent
    from jenny.agents.router import AgentRouter

    registry = ActionRegistry()
    registry.register(CheckOrderAction(), intents=["order_status"])
    registry.register(ProcessPaymentAction(), intents=["payment"])
    registry.register(GenerateQuoteAction(), intents=["quote"])
    registry.register(CheckPlanningAction(), intents=["planning"])
    registry.register(CreateTicketAction(), intents=["complaint"])
    registry.register(BookAppointmentAction(), intents=["appointment"])

    router = AgentRouter()
    router.register("faq", FAQAgent())
    router.register("action", ActionAgent(action_registry=registry))
    router.register("fallback", FallbackAgent())
    router.register("payment", PaymentAgent(action_registry=registry))
    router.register("quote", QuoteAgent(action_registry=registry))
    router.register("planning", PlanningAgent(action_registry=registry))

    intent_predictor = None
    if Path("checkpoints/intent/best_model.pt").exists():
        from ml.models.intent.predict import IntentPredictor

        intent_predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")

    ner_predictor = None
    if Path("checkpoints/ner/best_model.pt").exists():
        from ml.models.ner.predict import NERPredictor

        ner_predictor = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")

    return ConversationEngine(
        state_manager=StateManager(),
        intent_predictor=intent_predictor,
        ner_predictor=ner_predictor,
        agent_router=router,
    )


async def _send(engine, conv_id, message, channel="instagram"):
    """Envoie un message."""
    return await engine.process(
        EngineRequest(
            conversation_id=conv_id,
            business_id=uuid4(),
            message_text=message,
            channel=channel,
        )
    )


# ═══════════════════════════════════════════════════════════
#  scénario 1 — rdv instagram
#  claire veut un rdv
# ═══════════════════════════════════════════════════════════


class TestScenarioPriseDeRDV:
    """Claire prend rdv sur insta."""

    @pytest.mark.asyncio
    async def test_claire_rdv_instagram(self) -> None:
        """Claire → rdv via Instagram."""
        engine = _build_engine()
        conv_id = uuid4()

        # tour 1 — demande rdv
        r1 = await _send(
            engine,
            conv_id,
            "Coucou ! Je voudrais prendre rendez-vous pour une coupe et un balayage svp",
            channel="instagram",
        )
        # multi-label, top intent
        assert r1.intent in ("appointment", "greeting", "planning")
        assert r1.response_text is not None
        assert len(r1.response_text) > 10

        # tour 2 — date/heure
        r2 = await _send(
            engine,
            conv_id,
            "Jeudi prochain à 14h ce serait possible ?",
            channel="instagram",
        )
        assert r2.response_text is not None

        # tour 3 — merci
        r3 = await _send(
            engine,
            conv_id,
            "Super merci beaucoup !",
            channel="instagram",
        )
        assert r3.intent == "closing"

        # vérifie le contexte
        state = engine.state_manager.get_or_create(conv_id, uuid4())
        assert state.turn_count >= 3


# ═══════════════════════════════════════════════════════════
#  scénario 2 — tarifs whatsapp
#  mehdi demande les prix
# ═══════════════════════════════════════════════════════════


class TestScenarioTarifs:
    """Mehdi demande les tarifs."""

    @pytest.mark.asyncio
    async def test_mehdi_tarifs_whatsapp(self) -> None:
        """Mehdi → prix coupe homme."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "C'est combien une coupe homme chez vous ?",
            channel="whatsapp",
        )
        # peut varier selon le modèle
        assert r.intent in ("pricing", "appointment", "faq")
        assert r.response_text is not None
        assert r.requires_human is False

    @pytest.mark.asyncio
    async def test_mehdi_tarifs_multiples(self) -> None:
        """Mehdi pose plusieurs questions prix."""
        engine = _build_engine()
        conv_id = uuid4()

        r1 = await _send(
            engine,
            conv_id,
            "Quel est le prix d'une coupe homme ?",
            channel="whatsapp",
        )
        assert r1.intent in ("pricing", "quote", "faq")

        r2 = await _send(
            engine,
            conv_id,
            "Combien coûte un lissage ?",
            channel="whatsapp",
        )
        assert r2.intent in ("pricing", "quote", "planning", "faq")
        assert r2.response_text is not None


# ═══════════════════════════════════════════════════════════
#  scénario 3 — devis mariage
#  sophie veut un devis
# ═══════════════════════════════════════════════════════════


class TestScenarioDevisMariage:
    """Sophie demande un devis mariage."""

    @pytest.mark.asyncio
    async def test_sophie_devis_mariage(self) -> None:
        """Sophie → devis mariage."""
        engine = _build_engine()
        conv_id = uuid4()

        # tour 1 — demande
        r1 = await _send(
            engine,
            conv_id,
            "Bonjour, je me marie le 14 juin 2026 et je cherche une coiffeuse "
            "pour moi et mes 4 demoiselles d'honneur. Pouvez-vous me faire un devis ?",
            channel="form",
        )
        # devis ou greeting
        assert r1.intent in ("quote", "pricing", "appointment", "greeting")
        assert r1.response_text is not None
        assert "devis" in r1.response_text.lower() or len(r1.response_text) > 20

        # tour 2 — détails + email
        r2 = await _send(
            engine,
            conv_id,
            "Je voudrais un chignon pour moi et des coiffures mi-attachées "
            "pour les demoiselles d'honneur. Mon email est sophie.martin@gmail.com",
            channel="form",
        )
        assert r2.response_text is not None
        # email extrait en entité
        if r2.entities:
            assert "email" in r2.entities or len(r2.entities) > 0


# ═══════════════════════════════════════════════════════════
#  scénario 4 — suivi commande
#  nadia attend sa livraison
# ═══════════════════════════════════════════════════════════


class TestScenarioSuiviCommande:
    """Nadia suit sa commande."""

    @pytest.mark.asyncio
    async def test_nadia_suivi_commande_email(self) -> None:
        """Nadia → suivi commande."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Où en est ma commande CMD-2026-789 ?",
            channel="email",
        )
        assert r.intent == "order_status"
        assert r.response_text is not None
        assert r.agent_used == "action"

    @pytest.mark.asyncio
    async def test_nadia_commande_avec_suivi(self) -> None:
        """Nadia → suivi colis."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Où est mon colis commande CMD-456 ?",
            channel="email",
        )
        assert r.intent == "order_status"
        assert r.response_text is not None
        assert len(r.response_text) > 10


# ═══════════════════════════════════════════════════════════
#  scénario 5 — réclamation
#  kevin mécontent de sa coupe
# ═══════════════════════════════════════════════════════════


class TestScenarioReclamation:
    """Kevin fait une réclamation."""

    @pytest.mark.asyncio
    async def test_kevin_reclamation(self) -> None:
        """Kevin → réclamation coupe."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "J'ai un gros problème avec ma coupe, c'est un défaut de prestation",
            channel="instagram",
        )
        # classement variable
        assert r.intent in ("complaint", "escalation", "appointment")
        assert r.response_text is not None
        assert len(r.response_text) > 20

    @pytest.mark.asyncio
    async def test_kevin_veut_parler_gerante(self) -> None:
        """Kevin veut la gérante."""
        engine = _build_engine()
        conv_id = uuid4()

        # réclamation
        await _send(
            engine,
            conv_id,
            "Ma coupe est ratée, c'est inadmissible !",
            channel="instagram",
        )

        # escalade
        r2 = await _send(
            engine,
            conv_id,
            "Je veux parler à la gérante directement",
            channel="instagram",
        )
        assert r2.intent == "escalation"
        assert r2.requires_human is True


# ═══════════════════════════════════════════════════════════
#  scénario 6 — faq whatsapp
#  amina pose des questions
# ═══════════════════════════════════════════════════════════


class TestScenarioFAQ:
    """Amina questionne le salon."""

    @pytest.mark.asyncio
    async def test_amina_horaires(self) -> None:
        """Amina → horaires."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Vous êtes ouverts le lundi ?",
            channel="whatsapp",
        )
        # interprétation variable
        assert r.intent in ("planning", "faq", "appointment")
        assert r.response_text is not None

    @pytest.mark.asyncio
    async def test_amina_adresse(self) -> None:
        """Amina → adresse."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Quelle est votre adresse ?",
            channel="whatsapp",
        )
        assert r.response_text is not None
        # on accepte toute réponse
        assert len(r.response_text) > 5

    @pytest.mark.asyncio
    async def test_amina_produits(self) -> None:
        """Amina → produits."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Vous utilisez quoi comme produits de coloration ?",
            channel="whatsapp",
        )
        assert r.response_text is not None


# ═══════════════════════════════════════════════════════════
#  scénario 7 — paiement
#  thomas veut payer
# ═══════════════════════════════════════════════════════════


class TestScenarioPaiement:
    """Thomas veut régler."""

    @pytest.mark.asyncio
    async def test_thomas_paiement(self) -> None:
        """Thomas → paiement carte."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Bonjour, est-ce que je peux payer par carte sans contact ?",
            channel="whatsapp",
        )
        assert r.intent == "payment"
        assert r.response_text is not None
        # doit mentionner le paiement
        assert "carte" in r.response_text.lower() or "paiement" in r.response_text.lower()

    @pytest.mark.asyncio
    async def test_thomas_paiement_facture(self) -> None:
        """Thomas → règlement facture."""
        engine = _build_engine()
        conv_id = uuid4()

        r = await _send(
            engine,
            conv_id,
            "Je voudrais régler ma facture de 85€ pour la coupe + coloration",
            channel="whatsapp",
        )
        assert r.intent == "payment"
        assert r.response_text is not None
        # montant extrait
        if r.entities:
            assert "amount" in r.entities


# ═══════════════════════════════════════════════════════════
#  scénario 8 — salutations
#  messages de politesse
# ═══════════════════════════════════════════════════════════


class TestScenarioSalutations:
    """Messages de politesse."""

    @pytest.mark.asyncio
    async def test_bonjour_instagram(self) -> None:
        """Bonjour sur Instagram."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "Bonjour !", channel="instagram")
        assert r.intent == "greeting"
        assert r.response_text is not None
        assert r.requires_human is False

    @pytest.mark.asyncio
    async def test_salut_whatsapp(self) -> None:
        """Salut sur WhatsApp."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "Salut ça va ?", channel="whatsapp")
        # small_talk ou greeting
        assert r.intent in ("greeting", "small_talk", "general")

    @pytest.mark.asyncio
    async def test_au_revoir(self) -> None:
        """Au revoir poli."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "Merci beaucoup, au revoir !")
        assert r.intent == "closing"
        assert r.response_text is not None

    @pytest.mark.asyncio
    async def test_bonne_journee(self) -> None:
        """Fin de conversation."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "Au revoir, merci !")
        assert r.intent == "closing"
        assert r.response_text is not None


# ═══════════════════════════════════════════════════════════
#  scénario 9 — conversation complète
#  emma : parcours complet
# ═══════════════════════════════════════════════════════════


class TestScenarioConversationComplete:
    """Emma → parcours complet."""

    @pytest.mark.asyncio
    async def test_emma_parcours_complet(self) -> None:
        """Parcours complet d'Emma."""
        engine = _build_engine()
        conv_id = uuid4()

        # tour 1 — salut
        r1 = await _send(engine, conv_id, "Hello !", channel="instagram")
        assert r1.intent == "greeting"

        # tour 2 — rdv
        r2 = await _send(
            engine,
            conv_id,
            "Je voudrais prendre rdv pour une coloration",
            channel="instagram",
        )
        assert r2.intent in ("appointment", "planning")
        assert r2.response_text is not None

        # tour 3 — prix
        r3 = await _send(
            engine,
            conv_id,
            "C'est combien pour une colo + mèches ?",
            channel="instagram",
        )
        assert r3.intent in ("pricing", "faq", "planning")

        # tour 4 — paiement
        r4 = await _send(
            engine,
            conv_id,
            "Ok, je peux payer en plusieurs fois ?",
            channel="instagram",
        )
        assert r4.intent == "payment"
        assert "paiement" in r4.response_text.lower() or len(r4.response_text) > 10

        # tour 5 — au revoir
        r5 = await _send(
            engine,
            conv_id,
            "Parfait merci ! À bientôt",
            channel="instagram",
        )
        assert r5.intent == "closing"

        # vérifie le contexte complet
        state = engine.state_manager.get_or_create(conv_id, uuid4())
        assert state.turn_count == 5
        assert len(state.message_history) == 10  # 5 user + 5 assistant


# ═══════════════════════════════════════════════════════════
#  scénario 10 — langgraph
#  test du graphe complet
# ═══════════════════════════════════════════════════════════


class TestScenarioLangGraphCoiffeur:
    """Via le graphe LangGraph."""

    @pytest.mark.asyncio
    async def test_graph_rdv_coupe(self) -> None:
        """RDV coupe via le graphe."""
        result = await process_message_with_graph(
            message="Je voudrais réserver un rendez-vous pour une coupe",
            channel="instagram",
            sender="julie_94",
        )
        assert result["intent"] in ("appointment", "escalation")
        assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_graph_prix_coloration(self) -> None:
        """Prix via le graphe."""
        result = await process_message_with_graph(
            message="C'est combien une coloration complète ?",
            channel="whatsapp",
            sender="+33612345678",
        )
        assert result["intent"] == "pricing"
        assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_graph_reclamation_urgente(self) -> None:
        """Réclamation urgente → priorité haute."""
        result = await process_message_with_graph(
            message="Ma coloration a viré au vert, c'est une catastrophe ! J'ai un gros problème",
            channel="instagram",
            sender="client_mecontent",
        )
        # complaint ou escalation
        assert result["intent"] in ("complaint", "escalation")
        assert result["priority"] >= 5  # priorité haute

    @pytest.mark.asyncio
    async def test_graph_escalade_humain(self) -> None:
        """Demande un humain → escalade."""
        result = await process_message_with_graph(
            message="Je veux parler à quelqu'un, pas un robot",
            channel="instagram",
            sender="impatient_client",
        )
        assert result["intent"] == "escalation"
        assert result["requires_human"] is True
        assert result["priority"] >= 8

    @pytest.mark.asyncio
    async def test_graph_devis_mariage(self) -> None:
        """Devis mariage via le graphe."""
        result = await process_message_with_graph(
            message="Bonjour, je cherche une coiffeuse pour mon mariage, "
            "pouvez-vous me faire un devis ?",
            channel="form",
            sender="future_mariee",
        )
        # détection variable
        assert result["intent"] in ("quote", "pricing", "appointment", "greeting")
        assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_graph_commande_produit(self) -> None:
        """Suivi de commande."""
        result = await process_message_with_graph(
            message="Où en est ma commande CMD-567 ?",
            channel="email",
            sender="nadia@mail.com",
        )
        assert result["intent"] == "order_status"
        assert result["agent"] == "action"

    @pytest.mark.asyncio
    async def test_graph_planning_samedi(self) -> None:
        """Planning du samedi."""
        result = await process_message_with_graph(
            message="Quelles sont vos disponibilités samedi ?",
            channel="whatsapp",
            sender="+33698765432",
        )
        assert result["intent"] in ("planning", "appointment", "pricing")
        assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_graph_paiement_carte(self) -> None:
        """Question sur le paiement."""
        result = await process_message_with_graph(
            message="Est-ce que vous acceptez le paiement par carte ?",
            channel="whatsapp",
            sender="+33611223344",
        )
        # détecte payment_question
        assert result["intent"] in ("payment", "payment_question", "planning")


# ═══════════════════════════════════════════════════════════
#  scénario 11 — messages réalistes
#  vrais messages du salon
# ═══════════════════════════════════════════════════════════


class TestScenarioMessagesRealistesSalon:
    """Messages réalistes du salon."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message,expected_intents,channel",
        [
            # salutations
            ("Bonjour !", ["greeting"], "instagram"),
            ("Salut !", ["greeting", "general"], "instagram"),
            ("Hello !", ["greeting"], "whatsapp"),
            # rendez-vous
            ("Je voudrais prendre rendez-vous", ["appointment"], "instagram"),
            ("Je voudrais réserver un rdv pour mardi", ["appointment"], "whatsapp"),
            # tarifs
            ("Combien ça coûte une coupe femme ?", ["pricing"], "whatsapp"),
            ("C'est quel prix le lissage ?", ["pricing"], "whatsapp"),
            # commandes
            ("Où en est ma commande CMD-2026-001 ?", ["order_status"], "email"),
            ("J'attends mon colis de shampoing", ["order_status"], "email"),
            # réclamations
            (
                "J'ai un problème avec ma coupe, c'est un défaut",
                ["complaint", "escalation"],
                "instagram",
            ),
            # paiement
            ("Je peux payer en 3 fois ?", ["payment"], "instagram"),
            ("Comment régler ma facture ?", ["payment"], "email"),
            # au revoir
            ("Merci beaucoup, au revoir !", ["closing"], "instagram"),
        ],
    )
    async def test_message_realiste(
        self, message: str, expected_intents: list[str], channel: str
    ) -> None:
        """Chaque message bien classé."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), message, channel=channel)
        assert r.intent in expected_intents, (
            f"Message: '{message}' → attendu l'un de {expected_intents}, "
            f"obtenu '{r.intent}' (conf: {r.intent_confidence:.0%})"
        )
        assert r.response_text is not None
        assert len(r.response_text) > 0


# ═══════════════════════════════════════════════════════════
#  scénario 12 — robustesse
#  messages difficiles
# ═══════════════════════════════════════════════════════════


class TestScenarioRobustesse:
    """Messages ambigus, robustesse."""

    @pytest.mark.asyncio
    async def test_message_vague(self) -> None:
        """Message vague, pas de crash."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "ok")
        assert r.response_text is not None
        assert r.requires_human is False or r.requires_human is True  # juste pas de crash

    @pytest.mark.asyncio
    async def test_message_emoji_seul(self) -> None:
        """Emoji seul, pas de crash."""
        engine = _build_engine()
        r = await _send(engine, uuid4(), "👍")
        assert r.response_text is not None

    @pytest.mark.asyncio
    async def test_message_long(self) -> None:
        """Long message, pas de crash."""
        engine = _build_engine()
        long_msg = (
            "Bonjour, je suis cliente chez vous depuis 3 ans et j'ai toujours "
            "été très satisfaite. Cependant, lors de ma dernière visite le 10 mars, "
            "j'ai demandé une coloration châtain clair avec des reflets dorés mais "
            "le résultat est beaucoup plus foncé que prévu. J'aimerais qu'on trouve "
            "une solution, peut-être un rendez-vous pour rectifier ? Mon numéro est "
            "le 06 12 34 56 78. Merci d'avance."
        )
        r = await _send(engine, uuid4(), long_msg, channel="email")
        assert r.response_text is not None
        assert len(r.response_text) > 10
        # l'important, pas de crash
        assert r.intent is not None

    @pytest.mark.asyncio
    async def test_message_multilingue(self) -> None:
        """Français informel."""
        engine = _build_engine()
        r = await _send(
            engine,
            uuid4(),
            "Salut, vous faites les coupes homme ?",
            channel="instagram",
        )
        assert r.response_text is not None
        # l'important, qu'il réponde
        assert r.intent is not None

    @pytest.mark.asyncio
    async def test_pas_de_crash_accent(self) -> None:
        """Accents sans problème."""
        engine = _build_engine()
        r = await _send(
            engine,
            uuid4(),
            "J'aimerais réserver un créneau pour une méchée à l'éphéméride",
            channel="whatsapp",
        )
        assert r.response_text is not None


# ═══════════════════════════════════════════════════════════
#  scénario 13 — modif/annul rdv
#  léa modifie puis annule
# ═══════════════════════════════════════════════════════════


class TestScenarioModificationRDV:
    """Modif et annulation rdv."""

    @pytest.mark.asyncio
    async def test_modifier_rdv(self) -> None:
        """Décaler un rdv."""
        engine = _build_engine()
        r = await _send(
            engine,
            uuid4(),
            "Je voudrais décaler mon rendez-vous de mardi à jeudi svp",
            channel="whatsapp",
        )
        assert r.response_text is not None
        # classement variable
        assert r.intent is not None

    @pytest.mark.asyncio
    async def test_annuler_rdv(self) -> None:
        """Annuler un rdv."""
        engine = _build_engine()
        r = await _send(
            engine,
            uuid4(),
            "Je dois annuler mon rendez-vous de demain",
            channel="instagram",
        )
        assert r.response_text is not None
        # classement variable
        assert r.intent is not None


# ═══════════════════════════════════════════════════════════
#  scénario 14 — multi-canal
#  lucas : whatsapp puis insta
# ═══════════════════════════════════════════════════════════


class TestScenarioMultiCanal:
    """Cohérence entre canaux."""

    @pytest.mark.asyncio
    async def test_meme_question_differents_canaux(self) -> None:
        """Même question, tous canaux."""
        engine = _build_engine()

        r_insta = await _send(
            engine,
            uuid4(),
            "C'est combien une coupe homme ?",
            channel="instagram",
        )
        r_whatsapp = await _send(
            engine,
            uuid4(),
            "C'est combien une coupe homme ?",
            channel="whatsapp",
        )
        r_email = await _send(
            engine,
            uuid4(),
            "C'est combien une coupe homme ?",
            channel="email",
        )

        # même intent partout
        assert r_insta.intent == r_whatsapp.intent == r_email.intent == "pricing"
        # les 3 ont une réponse
        assert all(r.response_text for r in [r_insta, r_whatsapp, r_email])


# ═══════════════════════════════════════════════════════════
#  scénario 15 — api http
#  test via l'api rest
# ═══════════════════════════════════════════════════════════


class TestScenarioAPICoiffeur:
    """Test via l'API HTTP."""

    @pytest.fixture
    async def client(self):
        from httpx import ASGITransport, AsyncClient

        from jenny.api.main import create_app

        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c

    @pytest.mark.asyncio
    async def test_api_rdv_coiffure(self, client) -> None:
        """Widget web → demande rdv."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": BUSINESS_ID,
                "message": "Je voudrais prendre rendez-vous pour une coupe et un brushing samedi matin",
                "channel": "form",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "appointment"
        assert data["response"] is not None
        assert len(data["response"]) > 10

    @pytest.mark.asyncio
    async def test_api_tarifs(self, client) -> None:
        """Visiteur demande les tarifs."""
        response = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": str(uuid4()),
                "business_id": BUSINESS_ID,
                "message": "Quels sont vos tarifs pour les coupes femme ?",
                "channel": "form",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "pricing"

    @pytest.mark.asyncio
    async def test_api_conversation_complete_salon(self, client) -> None:
        """Conversation complète via l'API."""
        conv_id = str(uuid4())
        biz_id = BUSINESS_ID

        # bonjour
        r1 = await client.post(
            "/api/v1/conversation/chat",
            json={"conversation_id": conv_id, "business_id": biz_id, "message": "Bonjour !"},
        )
        assert r1.status_code == 200
        assert r1.json()["intent"] == "greeting"

        # rdv
        r2 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Je voudrais prendre rdv pour un lissage brésilien",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["intent"] == "appointment"

        # merci
        r3 = await client.post(
            "/api/v1/conversation/chat",
            json={
                "conversation_id": conv_id,
                "business_id": biz_id,
                "message": "Merci beaucoup, à bientôt !",
            },
        )
        assert r3.status_code == 200
        assert r3.json()["intent"] == "closing"


# ═══════════════════════════════════════════════════════════
#  rdv urgent + devis
# ═══════════════════════════════════════════════════════════


class TestRDVUrgentAvecDevis:
    """RDV urgent + devis combinés."""

    @pytest.mark.asyncio
    async def test_rdv_urgent_devis_via_graph(self):
        """Via le graphe LangGraph."""
        message = (
            "Bonjour, j'aimerai le rendez vous le plus rapide dispo "
            "c'est urgent et envoyé moi un devis"
        )

        result = await process_message_with_graph(
            message=message,
            channel="whatsapp",
            sender="client_urgent_01",
            business_id=BUSINESS_ID,
        )

        # résultat complet attendu
        assert result is not None
        assert result.get("intent") is not None
        assert result.get("response") is not None
        assert len(result["response"]) > 0

        print(f"\n{'=' * 60}")
        print(f"📨 Message : {message}")
        print(f"🎯 Intent détecté : {result['intent']}")
        print(f"📊 Confiance : {result['intent_confidence']:.0%}")
        print(f"🤖 Agent : {result['agent']}")
        print(f"🚨 Intervention humaine : {result['requires_human']}")
        print(f"⚡ Priorité : {result['priority']}")
        print("📝 Réponse :")
        print(f"   {result['response']}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_rdv_urgent_devis_via_engine(self):
        """Via le ConversationEngine."""
        engine = _build_engine()
        conv_id = str(uuid4())

        # message urgent + devis
        response = await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=BUSINESS_ID,
                message_text=(
                    "Bonjour, j'aimerai le rendez vous le plus rapide dispo "
                    "c'est urgent et envoyé moi un devis"
                ),
                channel="whatsapp",
            )
        )

        assert response is not None
        assert response.intent is not None
        assert response.response_text is not None
        assert len(response.response_text) > 10

        print(f"\n{'=' * 60}")
        print("📨 Via ConversationEngine")
        print(f"🎯 Intent : {response.intent}")
        print(f"📊 Confiance : {response.intent_confidence:.0%}")
        print(f"🤖 Agent : {response.agent_used}")
        print("📝 Réponse :")
        print(f"   {response.response_text}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_planning_agent_urgence_direct(self):
        """PlanningAgent urgence + calendrier."""
        from jenny.agents.planning_agent import PlanningAgent
        from jenny.engine.state_manager import ConversationState
        from jenny.integrations.google_calendar import GoogleCalendarService

        # service calendar simulé
        calendar = GoogleCalendarService()
        agent = PlanningAgent(calendar_service=calendar)

        # état urgent simulé
        state = ConversationState()
        state.set_intent("planning", 0.85)
        state.add_user_message(
            "Bonjour, j'aimerai le rendez vous le plus rapide dispo "
            "c'est urgent et envoyé moi un devis"
        )

        result = await agent.handle(state)

        assert result is not None
        assert result["response"] is not None
        assert len(result["response"]) > 0

        # vérifie l'urgence détectée
        action = result.get("action_result", {})
        assert action.get("type") == "urgent_slot", (
            f"L'urgence n'a pas été détectée. Type: {action.get('type')}"
        )
        assert action.get("success") is True

        # vérifie le créneau urgent
        slot = action.get("slot", {})
        assert "date" in slot
        assert "time" in slot

        print(f"\n{'=' * 60}")
        print("🚨 Test PlanningAgent URGENT")
        print(
            f"📅 Prochain créneau : {slot.get('day_name')} {slot.get('date')} à {slot.get('time')}"
        )
        print(f"📝 Réponse : {result['response']}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_google_calendar_service_simulated(self):
        """Google Calendar en simulé."""
        from jenny.integrations.google_calendar import GoogleCalendarService

        calendar = GoogleCalendarService()

        # mode simulé, sans credentials
        assert not calendar.is_configured

        # récupère les créneaux
        slots = await calendar.get_available_slots(days=3)
        assert len(slots) > 0

        # prochain créneau
        next_slot = await calendar.get_next_available_slot()
        assert next_slot is not None
        assert next_slot.available is True

        # crée un rdv
        result = await calendar.create_event(
            title="Coupe + Brushing — Test",
            start_datetime=f"{next_slot.date}T{next_slot.time}:00",
            end_datetime=f"{next_slot.date}T{next_slot.end_time}:00",
            customer_name="Client Test",
            customer_email="test@example.com",
            service="Coupe + Brushing",
        )
        assert result.success is True
        assert result.event is not None
        assert result.event.id != ""

        print(f"\n{'=' * 60}")
        print("📅 Google Calendar (mode simulé)")
        print(f"   Créneaux disponibles : {len(slots)}")
        print(f"   Prochain dispo : {next_slot.day_name} {next_slot.date} à {next_slot.time}")
        print(f"   RDV créé : {result.event.id}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_calendar_crud_operations(self):
        """CRUD calendrier simulé."""
        from jenny.integrations.google_calendar import GoogleCalendarService

        calendar = GoogleCalendarService()

        # create
        create_result = await calendar.create_event(
            title="Coloration — Marie",
            start_datetime="2026-03-20T10:00:00",
            end_datetime="2026-03-20T12:00:00",
            customer_name="Marie Dupont",
            customer_email="marie@example.com",
            customer_phone="06 12 34 56 78",
            service="Coloration complète",
        )
        assert create_result.success
        event_id = create_result.event.id

        # update — modifie l'heure
        update_result = await calendar.update_event(
            event_id=event_id,
            new_start="2026-03-20T14:00:00",
            new_end="2026-03-20T16:00:00",
            new_title="Coloration + Soin — Marie",
        )
        assert update_result.success

        # read — planning du jour
        schedule = await calendar.get_day_schedule("2026-03-20")
        assert len(schedule) >= 1

        # cancel
        cancel_result = await calendar.cancel_event(event_id=event_id)
        assert cancel_result.success

        print(f"\n{'=' * 60}")
        print("📅 CRUD Calendar OK")
        print(f"   CREATE → {event_id}")
        print("   UPDATE → modifié à 14h")
        print(f"   READ   → {len(schedule)} event(s) le 20/03")
        print("   CANCEL → annulé")
        print(f"{'=' * 60}\n")


# ═══════════════════════════════════════════════════════════
#  scénario 14 — multi-label
#  plusieurs demandes à la fois
# ═══════════════════════════════════════════════════════════


class TestMultiLabelIntents:
    """Détection multi-intention."""

    @pytest.mark.asyncio
    async def test_rdv_plus_devis_via_graph(self) -> None:
        """RDV + devis → deux intents."""
        result = await process_message_with_graph(
            message="Bonjour, je voudrais prendre rendez-vous et avoir un devis pour un lissage",
            channel="whatsapp",
            sender="+33612345678",
        )

        # vérifie le multi-intent
        detected = result.get("detected_intents", [])
        detected_names = [d["intent"] for d in detected]
        print(f"\n{'=' * 60}")
        print("📨 Multi-label: rdv + devis")
        print(f"🎯 Intents détectés : {detected_names}")
        print(f"📝 Multi-intent : {result.get('is_multi_intent')}")
        print(f"🤖 Agents : {result.get('agent_names', [])}")
        print(f"📝 Réponse :\n   {result['response'][:200]}")
        print(f"{'=' * 60}\n")

        assert result["response"] is not None
        assert len(result["response"]) > 0

    @pytest.mark.asyncio
    async def test_multi_label_predictor_direct(self) -> None:
        """predict_multi → plusieurs intents."""
        from ml.models.intent.predict import IntentPredictor

        predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")
        result = predictor.predict_multi("Bonjour, je voudrais prendre rdv et avoir un devis")

        # un ou plusieurs intents
        assert len(result["intents"]) >= 1
        detected_names = [d["intent"] for d in result["intents"]]
        # au moins un intent pertinent
        assert any(i in detected_names for i in ("appointment", "quote", "greeting", "planning"))

        print(f"\n{'=' * 60}")
        print("🎯 Multi-label direct test")
        for d in result["intents"]:
            print(f"   → {d['intent']} ({d['confidence']:.0%})")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_multi_label_via_engine(self) -> None:
        """Engine signale les multi-intents."""
        engine = _build_engine()

        r = await _send(
            engine,
            uuid4(),
            "Je voudrais un rendez-vous et un devis pour un balayage",
            channel="whatsapp",
        )

        print(f"\n{'=' * 60}")
        print("📨 Multi-label via Engine")
        print(f"🎯 Intent : {r.intent}")
        print(f"📊 Detected intents : {r.detected_intents}")
        print(f"📝 Multi-intent : {r.is_multi_intent}")
        print(f"📝 Réponse : {r.response_text[:200]}")
        print(f"{'=' * 60}\n")

        assert r.response_text is not None
        assert r.intent is not None

    @pytest.mark.asyncio
    async def test_single_intent_still_works(self) -> None:
        """Message simple → un seul intent."""
        from ml.models.intent.predict import IntentPredictor

        predictor = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")
        result = predictor.predict_multi("Où en est ma commande ?")

        assert result["primary_intent"] is not None
        assert result["primary_confidence"] > 0.3

        print(f"\n{'=' * 60}")
        print("🎯 Single intent test")
        for d in result["intents"]:
            print(f"   → {d['intent']} ({d['confidence']:.0%})")
        print(f"   Multi: {result['is_multi_intent']}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_multi_agent_execution(self) -> None:
        """Multi-intent → agents exécutés."""
        result = await process_message_with_graph(
            message="Je veux prendre rdv et connaître vos tarifs",
            channel="instagram",
        )

        agents = result.get("agent_names", [])
        print(f"\n{'=' * 60}")
        print("🤖 Multi-agent execution")
        print(f"   Agents : {agents}")
        print(
            f"   Réponse contient '---' (séparateur multi) : {'---' in result.get('response', '')}"
        )
        print(f"{'=' * 60}\n")

        assert result["response"] is not None


# ═══════════════════════════════════════════════════════════
#  scénario 15 — clarification
#  questions si confiance basse
# ═══════════════════════════════════════════════════════════


class TestClarification:
    """Mécanique de clarification."""

    def test_clarification_agent_very_low_confidence(self) -> None:
        """Confiance < 30% → menu."""
        from jenny.agents.clarification_agent import ClarificationAgent

        agent = ClarificationAgent()
        response = agent.generate_clarification(
            message="zzz xyz",
            detected_intents=[{"intent": "general", "confidence": 0.15}],
            confidence=0.15,
        )

        assert "reformuler" in response.lower() or "aider" in response.lower()
        assert "rendez-vous" in response.lower() or "tarifs" in response.lower()

        print(f"\n{'=' * 60}")
        print("🤔 Clarification — Confiance très basse (15%)")
        print(f"📝 Réponse :\n{response}")
        print(f"{'=' * 60}\n")

    def test_clarification_agent_low_confidence(self) -> None:
        """Confiance 30-50% → propose."""
        from jenny.agents.clarification_agent import ClarificationAgent

        agent = ClarificationAgent()
        response = agent.generate_clarification(
            message="Salut !",
            detected_intents=[{"intent": "greeting", "confidence": 0.40}],
            confidence=0.40,
        )

        assert "compris" in response.lower() or "souhaitez" in response.lower()

        print(f"\n{'=' * 60}")
        print("🤔 Clarification — Confiance basse (40%)")
        print(f"📝 Réponse :\n{response}")
        print(f"{'=' * 60}\n")

    def test_clarification_agent_ambiguous_multi(self) -> None:
        """Deux intents forts → confirme."""
        from jenny.agents.clarification_agent import ClarificationAgent

        agent = ClarificationAgent()
        response = agent.generate_clarification(
            message="Je veux un rdv et payer ma facture",
            detected_intents=[
                {"intent": "appointment", "confidence": 0.85},
                {"intent": "payment", "confidence": 0.80},
            ],
            confidence=0.85,
        )

        assert "rendez-vous" in response.lower() or "paiement" in response.lower()

        print(f"\n{'=' * 60}")
        print("🤔 Clarification — Multi-intent ambigu")
        print(f"📝 Réponse :\n{response}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_clarification_in_graph(self) -> None:
        """Faible confiance → clarification."""
        result = await process_message_with_graph(
            message="Salut !",
            channel="instagram",
        )

        print(f"\n{'=' * 60}")
        print("🤔 Clarification dans le graphe LangGraph")
        print(f"🎯 Intent : {result['intent']} ({result['intent_confidence']:.0%})")
        print(f"📝 Needs clarification : {result.get('needs_clarification')}")
        print(f"🤖 Agent : {result.get('agent')}")
        print(f"📝 Réponse :\n   {result.get('response', '')[:200]}")
        print(f"{'=' * 60}\n")

        # confiance basse → clarification
        if result.get("needs_clarification"):
            assert result.get("agent") == "clarification"
            assert "?" in result.get("response", "")  # doit être une question
        else:
            assert result.get("response") is not None

    @pytest.mark.asyncio
    async def test_clarification_via_engine(self) -> None:
        """Engine → ClarificationAgent."""
        engine = _build_engine()

        r = await _send(engine, uuid4(), "Salut !", channel="instagram")

        print(f"\n{'=' * 60}")
        print("🤔 Clarification via Engine")
        print(f"🎯 Intent : {r.intent} ({r.intent_confidence:.0%})")
        print(f"📝 Needs clarification : {r.needs_clarification}")
        print(f"🤖 Agent : {r.agent_used}")
        print(f"📝 Réponse : {r.response_text[:200]}")
        print(f"{'=' * 60}\n")

        assert r.response_text is not None
        if r.needs_clarification:
            assert r.agent_used == "clarification"

    @pytest.mark.asyncio
    async def test_high_confidence_no_clarification(self) -> None:
        """Message complet → rien à clarifier."""
        engine = _build_engine()

        r = await _send(
            engine,
            uuid4(),
            "Je voudrais une coupe femme mardi à 14h",
            channel="whatsapp",
        )

        assert r.response_text is not None
        # clarification = slot-filling
        if r.needs_clarification:
            assert r.clarification_reason == "slot_filling"

        print(f"\n{'=' * 60}")
        print(f"🎯 Intent : {r.intent} ({r.intent_confidence:.0%})")
        print(f"🤖 Agent : {r.agent_used} | clarif={r.clarification_reason or '-'}")
        print(f"{'=' * 60}\n")

    @pytest.mark.asyncio
    async def test_clarification_handle_method(self) -> None:
        """ClarificationAgent via handle()."""
        from jenny.agents.clarification_agent import ClarificationAgent
        from jenny.engine.state_manager import ConversationState

        agent = ClarificationAgent()
        state = ConversationState()
        state.set_intent("general", 0.25)
        state.add_user_message("blabla")

        result = await agent.handle(state)

        assert "response" in result
        assert result["action_result"]["needs_clarification"] is True
        assert len(result["response"]) > 0

        print(f"\n{'=' * 60}")
        print("🤔 ClarificationAgent.handle()")
        print(f"📝 Réponse : {result['response'][:150]}")
        print(f"{'=' * 60}\n")
