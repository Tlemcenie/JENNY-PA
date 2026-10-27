"""passe 2 moteur : règles et flux."""

from __future__ import annotations

import threading
from datetime import date
from typing import ClassVar
from uuid import uuid4

import pytest

from jenny.actions.base import BaseAction
from jenny.actions.registry import ActionRegistry
from jenny.agents.action_agent import ActionAgent
from jenny.agents.fallback_agent import FallbackAgent
from jenny.agents.router import AgentRouter
from jenny.engine.conversation_engine import (
    ConversationEngine,
    EngineRequest,
    accepts_offer,
    declines_offer,
    extract_customer_name,
    is_farewell,
    is_implicit_reschedule,
    looks_like_name,
    strip_farewell,
)
from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time
from jenny.engine.state_manager import ConversationState, StateManager

LUNDI = date(2026, 10, 26)
CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]


# ── fausses actions ──


class _Act(BaseAction):
    required_params: ClassVar[tuple[str, ...]] = ()

    def __init__(self, script: list[dict] | None = None) -> None:
        self.calls: list[dict] = []
        self.script = list(script or [])

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        if self.script:
            return dict(self.script.pop(0))
        return {"success": True}


class _Book(_Act):
    name = "book_appointment"

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        if self.script:
            return dict(self.script.pop(0))
        if not params.get("time"):
            return {"success": False, "propose_slots": True, "service": "Coupe femme"}
        return {"success": True, "appointment_id": f"rdv-{len(self.calls)}"}


class _Manage(_Act):
    name = "manage_appointment"

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        if self.script:
            return dict(self.script.pop(0))
        return {"success": True, "operation": params.get("operation"), "when": "jeudi 10h"}


class _Name(_Act):
    name = "set_customer_name"


class _Waitlist(_Act):
    name = "join_waitlist"


def _engine(book: list[dict] | None = None, manage: list[dict] | None = None, **kw):
    reg = ActionRegistry()
    acts = {
        "book": _Book(book),
        "manage": _Manage(manage),
        "name": _Name([{"success": True, "named": True, "name": "x"}] * 5),
        "waitlist": _Waitlist([{"success": True, "waitlisted": True}] * 5),
    }
    reg.register(acts["book"], intents=["appointment"])
    reg.register(acts["manage"], intents=["manage_appointment"])
    reg.register(acts["name"], intents=["set_customer_name"])
    reg.register(acts["waitlist"], intents=["join_waitlist"])
    router = AgentRouter()
    router.register("action", ActionAgent(action_registry=reg))
    router.register("fallback", FallbackAgent())
    sm = StateManager(redis_url="redis://localhost:1/0")
    return ConversationEngine(state_manager=sm, agent_router=router, **kw), acts


class _Fixed:
    """modèle qui dit toujours pareil"""

    def __init__(self, intent: str) -> None:
        self.intent = intent

    def predict_multi(self, text: str) -> dict:
        hit = {"intent": self.intent, "confidence": 0.92}
        return {"primary_intent": self.intent, "primary_confidence": 0.92, "intents": [hit]}


class _Chat:
    def __init__(self, eng: ConversationEngine) -> None:
        self.eng, self.conv, self.biz = eng, uuid4(), uuid4()

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz,
                message_text=msg,
                catalog_services=CATALOG,
            )
        )

    @property
    def state(self) -> ConversationState:
        return self.eng.state_manager.get(self.conv)


# ── négations ──


class TestNegations:
    @pytest.mark.parametrize(
        ("msg", "iso"),
        [
            ("pourquoi pas samedi", "2026-10-31"),
            ("Pourquoi pas samedi ?", "2026-10-31"),
            ("jeudi c'est pas un problème", "2026-10-29"),
            ("jeudi c'est pas un souci", "2026-10-29"),
            ("samedi ça me va pas mal", "2026-10-31"),
            ("demain ça va pas de souci", "2026-10-27"),
            ("demain, c'est pas grave", "2026-10-27"),
            ("samedi ce n'est pas un problème", "2026-10-31"),
        ],
    )
    def test_accord_garde_le_jour(self, msg: str, iso: str) -> None:
        assert parse_fr_date(msg, today=LUNDI).isoformat() == iso

    @pytest.mark.parametrize(
        "msg",
        [
            "pas samedi",
            "jeudi c'est pas possible",
            "samedi ça me va pas",
            "samedi ça m'arrange pas",
            "samedi ça ne m'arrange pas",
            "demain je peux pas",
            "jeudi ça va pas",
        ],
    )
    def test_vrai_refus(self, msg: str) -> None:
        assert parse_fr_date(msg, today=LUNDI) is None

    def test_refus_puis_autre_jour(self) -> None:
        assert parse_fr_date("pas demain mais jeudi", today=LUNDI).isoformat() == "2026-10-29"
        assert (
            parse_fr_date("demain je ne peux pas, plutôt jeudi", today=LUNDI).isoformat()
            == "2026-10-29"
        )

    def test_heures(self) -> None:
        assert parse_fr_time("pourquoi pas 14h").hour == 14
        assert parse_fr_time("pourquoi pas à 14h").hour == 14
        assert parse_fr_time("pas à 14h") is None
        assert parse_fr_time("pas à 14h mais 16h").hour == 16


# ── au revoir ──


class TestAuRevoir:
    @pytest.mark.parametrize(
        "msg",
        [
            "à demain 😊",
            "Top, à demain 😊",
            "merci 🙏 à demain",
            "À demain 🙂 merci",
            "à jeudi ✨",
            "Bon dimanche !",
            "Merci, bon lundi",
            "bon samedi à vous",
            "À mardi en huit !",
            "à demain, merci encore",
            "à demain et merci",
            "à demain alors merci",
            "bisous à demain",
            "à demain bisous",
            "À demain sans faute",
            "à demain, j'ai hâte",
            "Merci, à ce soir 18h !",
            "à cet aprem",
            "À dans 15 jours !",
            "Merci, à dans 15 jours",
            "À demain pour mon rendez-vous !",
            "Bonne soirée, à demain !",
        ],
    )
    def test_au_revoir(self, msg: str) -> None:
        assert is_farewell(msg, today=LUNDI)
        kw = {"today": LUNDI, "services": CATALOG, "booked": ("2026-10-30", "10:00")}
        for intent in (None, "appointment", "closing", "general"):
            assert not is_implicit_reschedule(msg, intent=intent, **kw)

    @pytest.mark.parametrize(
        "msg",
        [
            "Bon samedi 10h ça me va",
            "Jeudi 15h, bon week-end !",
            "à demain ?",
            "je peux attendre jusqu'à demain",
        ],
    )
    def test_pas_un_au_revoir(self, msg: str) -> None:
        assert not is_farewell(msg, today=LUNDI)

    @pytest.mark.parametrize(
        ("msg", "intent"),
        [
            ("Bonne soirée ! Vous ouvrez à quelle heure ?", "planning"),
            ("Bon week-end, je voudrais aussi un rdv pour ma fille", "appointment"),
        ],
    )
    @pytest.mark.asyncio
    async def test_souhait_plus_vraie_demande(self, msg: str, intent: str) -> None:
        # le souhait ne mange pas la demande
        eng, _ = _engine(intent_predictor=_Fixed(intent))
        r = await _Chat(eng).say(msg)
        assert r.intent == intent

    @pytest.mark.asyncio
    async def test_modele_trompe_sur_au_revoir(self) -> None:
        eng, acts = _engine(intent_predictor=_Fixed("appointment"))
        r = await _Chat(eng).say("À demain pour mon rendez-vous !")
        assert r.intent == "closing"
        assert acts["book"].calls == []

    def test_creneau_propose_garde_le_jour(self) -> None:
        # après des créneaux proposés
        assert strip_farewell("Merci, à jeudi 10h alors !").strip(" ,!") == "Merci"
        kept = strip_farewell("Merci, à jeudi 10h alors !", keep_days=True)
        assert parse_fr_date(kept, today=LUNDI) and parse_fr_time(kept)
        assert not is_farewell("Merci, à jeudi 10h alors !", today=LUNDI, keep_days=True)
        # souhaits toujours retirés
        assert is_farewell("Merci, bon week-end !", today=LUNDI, keep_days=True)

    def test_alternative_seulement_si_creneau(self) -> None:
        kw = {"today": LUNDI, "services": CATALOG, "booked": ("2026-10-30", "10:00")}
        assert is_implicit_reschedule("sinon jeudi ?", **kw)
        assert is_implicit_reschedule("et samedi ?", **kw)
        assert not is_implicit_reschedule("Et jeudi vous êtes ouverts ?", **kw)
        assert not is_implicit_reschedule("sinon jeudi vous fermez tard ?", **kw)


# ── noms ──


class TestNoms:
    @pytest.mark.parametrize(
        "msg",
        [
            "Mille mercis",
            "Grand merci",
            "Un grand merci !",
            "Bisous",
            "Bises",
            "peu importe",
            "n'importe",
            "c'est pareil",
            "aucune idée",
            "j'arrive",
            "tant pis",
            "laissez tomber",
            "Excellent",
            "Formidable",
            "Jenny",
            "c'est Jenny",
            "Merci Jenny",
            "Bravo Jenny",
        ],
    )
    def test_pas_un_nom(self, msg: str) -> None:
        assert extract_customer_name(msg, CATALOG) is None

    @pytest.mark.parametrize(
        ("msg", "name"),
        [
            ("Jenny Martin", "Jenny Martin"),
            ("Merci, Jenny Martin", "Jenny Martin"),
            ("C'est Marie, merci infiniment !", "Marie"),
            ("Marie, merci beaucoup !", "Marie"),
            ("D'Artagnan", "D'Artagnan"),
            ("Marie merci", "Marie"),
            ("Marie Dupont merci beaucoup !", "Marie Dupont"),
            ("merci Marie Dupont", "Marie Dupont"),
        ],
    )
    def test_vrai_nom(self, msg: str, name: str) -> None:
        assert extract_customer_name(msg, CATALOG) == name

    @pytest.mark.parametrize(
        "msg", ["Merci Léa", "merci madame Dupont", "Merci beaucoup Marie", "Jenny merci"]
    )
    def test_merci_a_quelqu_un(self, msg: str) -> None:
        assert extract_customer_name(msg, CATALOG) is None

    def test_looks_like_name(self) -> None:
        assert not looks_like_name("Jenny")
        assert looks_like_name("Jenny Martin")


# ── liste d'attente ──


class TestOffre:
    @pytest.mark.parametrize(
        "msg",
        [
            "ok",
            "Ok !",
            "oui",
            "Oui, avec plaisir",
            "d'accord merci",
            "Super, merci !",
            "go",
            "ok, inscrivez-moi",
            "d'accord, mettez-moi sur la liste",
            "Parfait, prévenez-moi",
            "ah je veux bien",
        ],
    )
    def test_accepte(self, msg: str) -> None:
        assert accepts_offer(msg)

    @pytest.mark.parametrize(
        "msg",
        [
            "Super, merci quand même",
            "Bon, tant pis",
            "ok je vais voir ailleurs",
            "non merci",
            "pas la peine",
            "Top mais une autre fois",
            "ok 14h",
            "parfait, et le 20 ?",
            "je vais réfléchir",
        ],
    )
    def test_pas_un_oui(self, msg: str) -> None:
        assert not accepts_offer(msg)

    def test_refus(self) -> None:
        assert declines_offer("Super, merci quand même")
        assert declines_offer("Bon, tant pis")
        assert not declines_offer("oui quand même")

    @pytest.mark.asyncio
    async def test_creneau_propose_puis_ok_14h(self) -> None:
        # complet, autre jour proposé, « Ok 14h »
        eng, acts = _engine(book=[{"success": False, "no_slots": True, "service": "Coupe femme"}])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain")
        assert chat.state.awaiting_waitlist is True
        r2 = await chat.say("Et le 20 ?")
        assert (r2.action_result or {}).get("propose_slots") is True
        assert chat.state.awaiting_waitlist is False
        r3 = await chat.say("Ok 14h")
        assert r3.intent == "appointment"
        assert acts["book"].calls[-1]["time"] == "14:00"
        assert acts["waitlist"].calls == []

    @pytest.mark.asyncio
    async def test_ok_avec_heure_pas_un_oui(self) -> None:
        # même armé, une heure = un créneau
        eng, acts = _engine(book=[{"success": False, "no_slots": True, "service": "Coupe femme"}])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain")
        r = await chat.say("ok 14h")
        assert r.intent != "join_waitlist"
        assert acts["waitlist"].calls == []

    @pytest.mark.asyncio
    async def test_merci_quand_meme(self) -> None:
        nope = {"success": False, "no_slots": True, "service": "Coupe femme"}
        eng, acts = _engine(book=[nope, nope, nope])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain")
        await chat.say("Je vais réfléchir")
        r = await chat.say("Super, merci quand même")
        assert r.intent != "join_waitlist"
        assert acts["waitlist"].calls == []
        assert chat.state.awaiting_waitlist is False


# ── créneau proposé + « à jeudi 10h » ──


class TestChoixDuCreneau:
    @pytest.mark.asyncio
    async def test_merci_a_demain_11h_reserve(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        r1 = await chat.say("je voudrais une coupe femme demain")
        assert (r1.action_result or {}).get("propose_slots") is True
        r2 = await chat.say("Merci, à demain 11h alors !")
        assert r2.intent == "appointment"
        assert acts["book"].calls[-1]["time"] == "11:00"

    @pytest.mark.asyncio
    async def test_bon_week_end_apres_propositions(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je voudrais une coupe femme demain")
        r = await chat.say("Merci, bon week-end !")
        assert r.intent != "appointment"
        assert len(acts["book"].calls) == 1

    @pytest.mark.asyncio
    async def test_report_refuse_puis_ok_a_jeudi(self) -> None:
        conflict = {
            "success": False,
            "operation": "reschedule",
            "conflict": True,
            "when": "vendredi 10h",
            "alternatives_text": "jeudi 10h, jeudi 11h",
        }
        eng, acts = _engine(manage=[conflict])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        r1 = await chat.say("je voudrais décaler à samedi 10h")
        assert (r1.action_result or {}).get("conflict") is True
        r2 = await chat.say("ok à jeudi 10h alors")
        assert r2.intent == "manage_appointment"
        sent = acts["manage"].calls[-1]
        assert sent["operation"] == "reschedule"
        assert sent["time"] == "10:00"
        assert parse_fr_date(sent["date"]).weekday() == 3


# ── nom + confirmation ──


class TestNomEtConfirmation:
    @pytest.mark.asyncio
    async def test_je_confirme_cest_marie(self) -> None:
        eng, acts = _engine(book=[{"success": True, "appointment_id": "rdv-1", "ask_name": True}])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("Je confirme, c'est Marie")
        assert r.intent == "set_customer_name"
        assert acts["name"].calls[-1]["name"] == "Marie"
        assert acts["manage"].calls[-1]["operation"] == "confirm"
        assert (r.action_result or {}).get("confirmed") is True
        st = chat.state
        assert st.awaiting_confirmation is False
        assert "operation" not in st.slots
        assert st.current_intent == "set_customer_name"

    @pytest.mark.asyncio
    async def test_oui_cest_marie_ne_confirme_pas(self) -> None:
        # « oui » répond au nom
        eng, acts = _engine(book=[{"success": True, "appointment_id": "rdv-1", "ask_name": True}])
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("Oui c'est Marie")
        assert acts["manage"].calls == []


# ── modèles en duck typing ──


class _HeadLike:
    """sans héritage"""

    def __init__(self) -> None:
        self.threads: list[str] = []

    def predict_multi(self, text: str) -> dict:
        self.threads.append(threading.current_thread().name)
        return {"primary_intent": "faq", "primary_confidence": 0.91, "intents": []}


class TestDuckTyping:
    @pytest.mark.asyncio
    async def test_modele_sans_heritage(self) -> None:
        head = _HeadLike()
        eng, _ = _engine(intent_predictor=head)
        r = await _Chat(eng).say("vous avez un parking ?")
        assert r.intent == "faq"
        assert r.intent_confidence == pytest.approx(0.91)
        # hors du thread principal
        main = threading.main_thread().name
        assert head.threads and all(t != main for t in head.threads)

    @pytest.mark.asyncio
    async def test_objet_sans_methode_ignore(self) -> None:
        eng, _ = _engine(intent_predictor=object())
        r = await _Chat(eng).say("je voudrais un rdv")
        assert r.intent == "appointment"


# ── seuil du routeur ──


class TestRouteur:
    @pytest.mark.asyncio
    async def test_seuil_partage(self, monkeypatch) -> None:
        import jenny.agents.router as router_mod

        seen: list[str] = []

        class _Agent:
            name = "x"

            def __init__(self, label: str) -> None:
                self.label = label

            async def handle(self, state) -> dict:
                seen.append(self.label)
                return {"documents": [], "action_result": None}

        router = AgentRouter()
        router.register("faq", _Agent("faq"))
        router.register("fallback", _Agent("fallback"))
        state = ConversationState()
        state.set_intent("faq", 0.5)
        await router.route(state)
        monkeypatch.setattr(router_mod, "LOW_CONFIDENCE_FLOOR", 0.6)
        await router.route(state)
        assert seen == ["faq", "fallback"]


# ── grounding rag ──


class TestGrounding:
    @pytest.mark.asyncio
    async def test_docs_filtres_comme_la_faq(self) -> None:
        from types import SimpleNamespace

        class _Retriever:
            async def search(self, query, *, business_id, top_k, score_threshold):
                hits = [(0.9, "parking gratuit"), (0.6, "horaires"), (0.36, "bruit")]
                return [
                    SimpleNamespace(content=c, score=s, metadata={})
                    for s, c in hits
                    if s >= score_threshold
                ]

        eng, _ = _engine(retriever=_Retriever())
        chat = _Chat(eng)
        await chat.say("vous avez un parking ?")
        docs = chat.state.retrieved_documents
        # écart au meilleur > 0.20 : écarté
        assert [d["content"] for d in docs] == ["parking gratuit"]
