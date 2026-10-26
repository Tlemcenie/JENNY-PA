"""tests du moteur : slots, verrous, débit."""

import asyncio
import time as _time
from datetime import date, timedelta
from typing import ClassVar
from uuid import uuid4

import pytest

from jenny.actions.base import BaseAction
from jenny.actions.registry import ActionRegistry
from jenny.agents.action_agent import ActionAgent
from jenny.agents.fallback_agent import FallbackAgent
from jenny.agents.faq_agent import FAQ_MIN_SCORE
from jenny.agents.router import AgentRouter
from jenny.engine.conversation_engine import (
    ConversationEngine,
    EngineRequest,
    accepts_offer,
    coerce_entity,
    detect_appointment_mgmt,
    extract_customer_name,
    is_confirmation,
    is_farewell,
    is_implicit_reschedule,
    looks_like_name,
    strip_farewell,
)
from jenny.engine.datetime_fr import today_in
from jenny.engine.state_manager import StateManager
from jenny.engine.thresholds import LATCH_MAX_TURNS

LUNDI = date(2026, 10, 26)
CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]


# ── fausses actions métier ──


class _Recorder(BaseAction):
    """garde les appels"""

    required_params: ClassVar[tuple[str, ...]] = ()

    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result or {"success": True}

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        return dict(self.result)


class _Book(_Recorder):
    name = "book_appointment"

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        if self.result.get("no_slots"):
            return dict(self.result)
        if not params.get("time"):
            return {"success": False, "propose_slots": True}
        # comme le vrai handler
        int(params.get("duration") or 30)
        return {"success": True, "appointment_id": f"rdv-{len(self.calls)}", **self.result}


class _Manage(_Recorder):
    name = "manage_appointment"

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        return {"success": True, "operation": params.get("operation")}


class _Name(_Recorder):
    name = "set_customer_name"


class _Phone(_Recorder):
    name = "set_customer_phone"


class _Waitlist(_Recorder):
    name = "join_waitlist"


def _engine(book_result: dict | None = None, name_result: dict | None = None, **kw):
    reg = ActionRegistry()
    acts = {
        "book": _Book(book_result),
        "manage": _Manage(),
        "name": _Name(name_result or {"success": True, "named": True}),
        "phone": _Phone({"success": True, "phoned": True}),
        "waitlist": _Waitlist({"success": True, "waitlisted": True}),
    }
    reg.register(acts["book"], intents=["appointment"])
    reg.register(acts["manage"], intents=["manage_appointment"])
    reg.register(acts["name"], intents=["set_customer_name"])
    reg.register(acts["phone"], intents=["set_customer_phone"])
    reg.register(acts["waitlist"], intents=["join_waitlist"])
    router = AgentRouter()
    router.register("action", ActionAgent(action_registry=reg))
    router.register("fallback", FallbackAgent())
    sm = StateManager(redis_url="redis://localhost:1/0")  # mémoire
    eng = ConversationEngine(state_manager=sm, agent_router=router, **kw)
    return eng, acts


class _Chat:
    def __init__(self, eng: ConversationEngine, tz: str | None = None) -> None:
        self.eng, self.conv, self.biz, self.tz = eng, uuid4(), uuid4(), tz

    async def say(self, msg: str):
        return await self.eng.process(
            EngineRequest(
                conversation_id=self.conv,
                business_id=self.biz,
                message_text=msg,
                catalog_services=CATALOG,
                timezone=self.tz,
            )
        )

    @property
    def state(self):
        return self.eng.state_manager.get(self.conv)


# ── B2 : dates absolues ──


class TestDatesAbsolues:
    @pytest.mark.asyncio
    async def test_slot_en_iso(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        r = await chat.say("je réserve une coupe femme demain à 14h")
        assert (r.action_result or {}).get("success") is True
        sent = acts["book"].calls[-1]
        assert sent["date"] == (today_in("Europe/Paris") + timedelta(days=1)).isoformat()
        assert sent["time"] == "14:00"

    @pytest.mark.asyncio
    async def test_date_figee_au_premier_tour(self) -> None:
        # le jour ne bouge plus
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv pour une coupe femme demain")
        iso = chat.state.slots["date"].value
        assert iso == (today_in() + timedelta(days=1)).isoformat()
        await chat.say("à 15h")
        assert acts["book"].calls[-1]["date"] == iso
        assert acts["book"].calls[-1]["time"] == "15:00"

    @pytest.mark.asyncio
    async def test_fuseau_du_salon(self) -> None:
        for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
            eng, acts = _engine()
            chat = _Chat(eng, tz=tz)
            await chat.say("rdv balayage demain à 10h")
            assert acts["book"].calls[-1]["date"] == (today_in(tz) + timedelta(days=1)).isoformat()
            assert chat.state.business_timezone == tz


# ── B3 : purge après réservation ──


class TestPurgeApresRdv:
    @pytest.mark.asyncio
    async def test_nouvelle_prestation_ne_reserve_pas(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        r1 = await chat.say("je réserve une coupe femme demain à 10h")
        assert (r1.action_result or {}).get("success") is True
        st = chat.state
        assert "date" not in st.slots and "time" not in st.slots and "service" not in st.slots
        assert st.slots["appointment_id"].value == "rdv-1"
        r2 = await chat.say("je voudrais aussi un rdv pour un balayage")
        # pas de 2e rdv à l'ancienne date
        assert len(acts["book"].calls) == 1
        assert r2.clarification_reason == "slot_filling"
        assert chat.state.slots["service"].value == "Balayage"

    @pytest.mark.asyncio
    async def test_ancienne_prestation_pas_reprise(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("je voudrais un autre rdv")
        assert len(acts["book"].calls) == 1
        assert "service" not in chat.state.slots or not chat.state.slots["service"].filled

    @pytest.mark.asyncio
    async def test_id_garde_pour_annuler(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("finalement j'annule")
        assert r.intent == "manage_appointment"
        assert acts["manage"].calls[-1]["appointment_id"] == "rdv-1"
        assert acts["manage"].calls[-1]["operation"] == "cancel"
        # purge aussi l'opération
        assert "operation" not in chat.state.slots

    @pytest.mark.parametrize("bye", ["Merci, à demain !", "super, à jeudi alors", "à lundi"])
    @pytest.mark.asyncio
    async def test_au_revoir_ne_deplace_pas(self, bye: str) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        await chat.say(bye)
        assert acts["manage"].calls == []

    @pytest.mark.asyncio
    async def test_report_garde_le_jour(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("plutôt à 16h")
        sent = acts["manage"].calls[-1]
        assert sent["operation"] == "reschedule"
        assert sent["time"] == "16:00"
        # pas de vieux jour
        assert "date" not in sent


# ── report implicite : pas sur un au revoir ──


class TestReportImplicite:
    @pytest.mark.parametrize(
        "msg",
        [
            "Merci, bon week-end !",
            "Bon week-end à vous !",
            "À ce soir !",
            "Merci, à la semaine prochaine !",
            "je vous envoie la photo ce soir",
            "J'ai appelé ce matin",
            "Je vous rappelle tout à l'heure",
            "Je vous rappelle demain",
            "Vous êtes ouverts le week-end ?",
            "Vous fermez à quelle heure samedi ?",
            "à midi !",
            "Merci, à vendredi 10h !",
            "à vendredi 10h alors !",
            "On se voit vendredi alors",
            "la semaine prochaine à 15h",
            "dans un mois plutôt",
            "je voudrais un autre rdv jeudi",
        ],
    )
    @pytest.mark.asyncio
    async def test_bavardage_ne_deplace_pas(self, msg: str) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        r = await chat.say(msg)
        assert acts["manage"].calls == []
        assert r.intent != "manage_appointment"

    @pytest.mark.parametrize(
        ("msg", "date_set", "time_set"),
        [
            ("plutôt jeudi", True, False),
            ("et samedi ?", True, False),
            ("jeudi 15h", True, True),
            ("jeudi c'est possible ?", True, False),
            ("vous pouvez me mettre à 16h ?", False, True),
            ("Merci, plutôt jeudi alors", True, False),
            ("ce soir à 18h", True, True),
            ("je peux venir jeudi", True, False),
            ("16h", False, True),
            ("jeudi à midi", True, True),
            ("Bon samedi 10h ça me va", True, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_vrai_report(self, msg: str, date_set: bool, time_set: bool) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        r = await chat.say(msg)
        assert r.intent == "manage_appointment"
        sent = acts["manage"].calls[-1]
        assert sent["operation"] == "reschedule"
        assert ("date" in sent) is date_set
        assert ("time" in sent) is time_set

    @pytest.mark.parametrize("msg", ["vendredi 10h", "Vendredi alors !", "vendredi", "10h"])
    @pytest.mark.asyncio
    async def test_meme_creneau_ne_bouge_pas(self, msg: str) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        await chat.say(msg)
        assert acts["manage"].calls == []

    @pytest.mark.asyncio
    async def test_creneau_suit_le_report(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        await chat.say("plutôt jeudi")
        assert len(acts["manage"].calls) == 1
        st = chat.state
        # jour neuf, heure gardée
        assert st.booked_date == acts["manage"].calls[0]["date"]
        assert st.booked_time == "10:00"
        await chat.say("jeudi alors !")
        assert len(acts["manage"].calls) == 1

    @pytest.mark.asyncio
    async def test_annulation_oublie_le_creneau(self) -> None:
        eng, _ = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        assert chat.state.booked_time == "10:00"
        await chat.say("finalement j'annule")
        assert chat.state.booked_date is None and chat.state.booked_time is None

    @pytest.mark.parametrize("bye", ["Bon week-end à vous !", "À ce soir !", "À demain !"])
    @pytest.mark.asyncio
    async def test_au_revoir_en_cours_ne_reserve_pas(self, bye: str) -> None:
        # rdv en cours, heure déjà donnée
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv à 15h pour une coupe femme")
        assert acts["book"].calls == []
        r = await chat.say(bye)
        assert acts["book"].calls == []
        assert r.intent != "appointment"
        assert "date" not in chat.state.slots

    @pytest.mark.parametrize("answer", ["ce soir", "le week-end", "jeudi"])
    @pytest.mark.asyncio
    async def test_vraie_reponse_en_cours(self, answer: str) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv à 15h pour une coupe femme")
        r = await chat.say(answer)
        assert r.intent == "appointment"
        assert acts["book"].calls[-1]["time"] == "15:00"
        assert acts["book"].calls[-1]["date"]

    @pytest.mark.parametrize(
        "msg", ["je réserve une coupe femme jeudi à midi", "rdv coupe femme demain, à 10h"]
    )
    @pytest.mark.asyncio
    async def test_midi_reste_une_heure(self, msg: str) -> None:
        eng, acts = _engine()
        r = await _Chat(eng).say(msg)
        assert r.intent == "appointment"
        assert acts["book"].calls[-1]["time"] in ("12:00", "10:00")
        assert acts["book"].calls[-1]["date"]

    @pytest.mark.asyncio
    async def test_merci_prestation_bon_weekend(self) -> None:
        eng, acts = _engine()
        r = await _Chat(eng).say("Merci pour la coupe femme, bon week-end !")
        assert r.intent != "appointment"
        assert acts["book"].calls == []

    def test_au_revoir(self) -> None:
        assert is_farewell("Merci, bon week-end !")
        assert is_farewell("À ce soir !")
        assert is_farewell("à jeudi 10h alors")
        assert is_farewell("Merci pour le rdv, à demain !")
        assert not is_farewell("une coupe ce week-end")
        assert not is_farewell("ce soir à 18h")
        # créneau en plus
        assert not is_farewell("Jeudi 15h, bon week-end !")
        # cible d'un report
        assert not is_farewell("Déplacez-le à jeudi")
        assert not is_farewell("je repousse à la semaine prochaine")
        assert (
            strip_farewell("Je décale à jeudi, bon week-end !").strip(" ,!") == "Je décale à jeudi"
        )

    @pytest.mark.parametrize(
        ("msg", "field"),
        [
            ("Déplacez-le à jeudi", "date"),
            ("je voudrais décaler à demain", "date"),
            ("je repousse mon rdv à la semaine prochaine", "date"),
            ("Je décale à jeudi, bon week-end !", "date"),
            ("on peut avancer à ce soir ?", "date"),
        ],
    )
    @pytest.mark.asyncio
    async def test_report_cible_gardee(self, msg: str, field: str) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme vendredi à 10h")
        r = await chat.say(msg)
        assert r.intent == "manage_appointment"
        assert acts["manage"].calls[-1]["operation"] == "reschedule"
        assert field in acts["manage"].calls[-1]

    def test_fonction_directe(self) -> None:
        kw = {"today": LUNDI, "services": CATALOG}
        assert is_implicit_reschedule("plutôt jeudi", **kw)
        assert not is_implicit_reschedule("Merci, bon week-end !", **kw)
        assert not is_implicit_reschedule("jeudi 15h, merci", **kw)
        assert not is_implicit_reschedule("jeudi", intent="closing", **kw)
        assert not is_implicit_reschedule("jeudi", booked=("2026-10-29", None), **kw)
        assert is_implicit_reschedule("jeudi", booked=("2026-10-30", "10:00"), **kw)
        # nouvelle prestation
        assert not is_implicit_reschedule("un balayage jeudi", **kw)


# ── B6 : verrous ──


class TestVerrous:
    @pytest.mark.asyncio
    async def test_nom_pas_desarme_par_deux_secondes(self) -> None:
        eng, acts = _engine(book_result={"ask_name": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        assert chat.state.awaiting_name is True
        r = await chat.say("deux secondes")
        assert r.intent != "set_customer_name"
        assert chat.state.awaiting_name is True
        r = await chat.say("Marie")
        assert r.intent == "set_customer_name"
        assert acts["name"].calls[-1]["name"] == "Marie"
        assert chat.state.awaiting_name is False

    @pytest.mark.asyncio
    async def test_nom_expire(self) -> None:
        eng, acts = _engine(book_result={"ask_name": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        for _ in range(LATCH_MAX_TURNS + 1):
            await chat.say("euh attends")
        assert chat.state.awaiting_name is False
        r = await chat.say("Marie")
        assert r.intent != "set_customer_name"
        assert acts["name"].calls == []

    @pytest.mark.asyncio
    async def test_telephone_attend(self) -> None:
        eng, acts = _engine(
            book_result={"ask_name": True},
            name_result={"success": True, "named": True, "ask_phone": True},
        )
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("Sophie")
        assert chat.state.awaiting_phone is True
        await chat.say("attendez je cherche")
        assert chat.state.awaiting_phone is True
        r = await chat.say("06 12 34 56 78")
        assert r.intent == "set_customer_phone"
        assert acts["phone"].calls[-1]["phone"] == "0612345678"
        assert chat.state.awaiting_phone is False

    @pytest.mark.asyncio
    async def test_liste_attente_hesitation_puis_oui(self) -> None:
        eng, acts = _engine(book_result={"success": False, "no_slots": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        assert chat.state.awaiting_waitlist is True
        await chat.say("hmm je réfléchis")
        assert chat.state.awaiting_waitlist is True
        r = await chat.say("oui")
        assert r.intent == "join_waitlist"
        assert len(acts["waitlist"].calls) == 1
        assert chat.state.awaiting_waitlist is False

    @pytest.mark.asyncio
    async def test_liste_attente_refus(self) -> None:
        eng, acts = _engine(book_result={"success": False, "no_slots": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("non merci")
        assert chat.state.awaiting_waitlist is False
        assert acts["waitlist"].calls == []

    @pytest.mark.asyncio
    async def test_autre_sujet_oublie_les_oui_non(self) -> None:
        # un « ok » plus tard n'inscrit pas
        eng, acts = _engine(book_result={"success": False, "no_slots": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("c'est combien un balayage ?")
        assert chat.state.awaiting_waitlist is False
        await chat.say("ok merci")
        assert acts["waitlist"].calls == []

    @pytest.mark.asyncio
    async def test_autre_sujet_oublie_la_confirmation(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        await chat.say("c'est combien un balayage ?")
        assert chat.state.awaiting_confirmation is False
        await chat.say("oui")
        assert acts["manage"].calls == []


# ── B7/B8 : politesse ≠ confirmation ──


class TestPolitesse:
    @pytest.mark.parametrize(
        "msg", ["Parfait, merci !", "super merci", "ok merci", "c'est bon", "Top !", "merci"]
    )
    def test_politesse_ne_confirme_pas(self, msg: str) -> None:
        assert detect_appointment_mgmt(msg, True) is None

    @pytest.mark.parametrize("msg", ["oui", "Oui merci", "ouais", "ça me va", "volontiers"])
    def test_vrai_oui(self, msg: str) -> None:
        assert detect_appointment_mgmt(msg, True) == "confirm"
        assert is_confirmation(msg)

    def test_confirm_explicite(self) -> None:
        assert detect_appointment_mgmt("je confirme", False) == "confirm"

    def test_offre(self) -> None:
        assert accepts_offer("ok") and accepts_offer("Oui, avec plaisir")
        assert not accepts_offer("non merci") and not accepts_offer("pas la peine")

    @pytest.mark.asyncio
    async def test_parfait_merci_ne_change_rien(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        assert chat.state.awaiting_confirmation is True
        r = await chat.say("Parfait, merci !")
        assert r.intent != "manage_appointment"
        assert acts["manage"].calls == []

    @pytest.mark.asyncio
    async def test_cest_bon_cest_marie(self) -> None:
        eng, acts = _engine(book_result={"ask_name": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("C'est bon, c'est Marie")
        assert r.intent == "set_customer_name"
        assert acts["name"].calls[-1]["name"] == "Marie"
        assert acts["manage"].calls == []

    @pytest.mark.asyncio
    async def test_oui_cest_marie_nom_prime(self) -> None:
        eng, acts = _engine(book_result={"ask_name": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("Oui c'est Marie Dupont")
        assert r.intent == "set_customer_name"
        assert acts["name"].calls[-1]["name"] == "Marie Dupont"
        assert acts["manage"].calls == []

    @pytest.mark.asyncio
    async def test_oui_confirme(self) -> None:
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("oui")
        assert r.intent == "manage_appointment"
        assert acts["manage"].calls[-1]["operation"] == "confirm"
        assert chat.state.awaiting_confirmation is False


class TestNoms:
    @pytest.mark.parametrize(
        ("msg", "name"),
        [
            ("Marie", "Marie"),
            ("C'est bon, c'est Marie", "Marie"),
            ("Oui c'est Marie Dupont", "Marie Dupont"),
            ("Sophie Martin, merci !", "Sophie Martin"),
            ("je m'appelle Léa et je voudrais un brushing", "Léa"),
            ("Jean de la Tour", "Jean de la Tour"),
        ],
    )
    def test_extrait(self, msg: str, name: str) -> None:
        assert extract_customer_name(msg, CATALOG) == name

    @pytest.mark.parametrize(
        "msg",
        [
            "deux secondes",
            "Parfait, merci !",
            "Balayage",
            "jeudi",
            "attendez",
            "c'est quoi ?",
            "Rien",
        ],
    )
    def test_pas_un_nom(self, msg: str) -> None:
        assert extract_customer_name(msg, CATALOG) is None

    def test_looks_like_name_politesse(self) -> None:
        assert not looks_like_name("deux secondes")
        assert not looks_like_name("Parfait")
        assert not looks_like_name("c'est bon")
        assert looks_like_name("Camille Durand")

    @pytest.mark.parametrize(
        "msg",
        [
            "Merci beaucoup !",
            "Merci infiniment",
            "Merci Jenny",
            "Merci, Jenny !",
            "Merci madame",
            "Merci Marie",
            "Merci beaucoup Marie",
            "Oui avec plaisir",
            "Avec plaisir",
            "En fin de journée",
            "Un dégradé",
            "Les pointes",
            "Du volume",
            "madame",
        ],
    )
    def test_merci_et_mots_courants(self, msg: str) -> None:
        assert extract_customer_name(msg, CATALOG) is None

    @pytest.mark.parametrize(
        ("msg", "name"),
        [
            ("Super merci beaucoup, Marie Dupont", "Marie Dupont"),
            ("Merci, c'est Marie", "Marie"),
            ("Merci c'est Marie", "Marie"),
            ("Merci, Marie", "Marie"),
            ("Madame Dupont", "Madame Dupont"),
            ("Le Gall", "Le Gall"),
        ],
    )
    def test_nom_malgre_merci(self, msg: str, name: str) -> None:
        assert extract_customer_name(msg, CATALOG) == name

    def test_pas_le_nom_du_salon(self) -> None:
        assert extract_customer_name("Chez Lina", CATALOG) == "Chez Lina"
        assert extract_customer_name("Chez Lina", CATALOG, "Chez Lina") is None

    @pytest.mark.asyncio
    async def test_merci_beaucoup_puis_vrai_nom(self) -> None:
        eng, acts = _engine(book_result={"ask_name": True})
        chat = _Chat(eng)
        await chat.say("je réserve une coupe femme demain à 10h")
        r = await chat.say("Merci beaucoup !")
        assert r.intent != "set_customer_name"
        assert acts["name"].calls == []
        # verrou toujours armé
        assert chat.state.awaiting_name is True
        r = await chat.say("Marie")
        assert r.intent == "set_customer_name"
        assert acts["name"].calls[-1]["name"] == "Marie"


# ── B11 : entités filtrées ──


class TestCoercion:
    def test_duree(self) -> None:
        assert coerce_entity("duration", "30 min") == "30"
        assert coerce_entity("duration", "1h30") == "90"
        assert coerce_entity("duration", "beaucoup") is None

    def test_dates_heures(self) -> None:
        assert coerce_entity("date", "jeudi", today=LUNDI) == "2026-10-29"
        assert coerce_entity("date", "le", message="le 14 février", today=LUNDI) == "2027-02-14"
        assert coerce_entity("date", "bientôt") is None
        assert coerce_entity("time", "14h") == "14:00"
        assert coerce_entity("time", "vers midi") == "12:00"

    def test_liste_blanche(self) -> None:
        assert coerce_entity("operation", "cancel") is None
        assert coerce_entity("business_id", str(uuid4())) is None
        assert coerce_entity("appointment_id", "x") is None
        assert coerce_entity("misc", "x") is None

    def test_contacts(self) -> None:
        assert coerce_entity("email", "Test@Example.com") == "test@example.com"
        assert coerce_entity("email", "pas un mail") is None
        assert coerce_entity("phone", "06 12 34 56 78") == "06 12 34 56 78"
        assert coerce_entity("phone", "12") is None
        assert coerce_entity("amount", "150,50") == "150.50"
        assert coerce_entity("amount", "beaucoup") is None
        assert coerce_entity("service", "  coupe  ") == "coupe"
        assert coerce_entity("service", "x" * 500) == "x" * 120
        assert coerce_entity("name", "") is None

    @pytest.mark.asyncio
    async def test_ner_filtree_dans_le_moteur(self) -> None:
        from ml.models.ner.predict import NERPredictor

        class _FakeNER(NERPredictor):
            def __init__(self) -> None:
                pass

            def predict(self, text: str) -> dict[str, str]:
                return {"duration": "30 min", "bogus": "x", "operation": "cancel"}

        eng, acts = _engine(ner_predictor=_FakeNER())
        chat = _Chat(eng)
        r = await chat.say("je réserve une coupe femme demain à 10h")
        # pas de crash int()
        assert (r.action_result or {}).get("success") is True
        sent = acts["book"].calls[-1]
        assert sent["duration"] == "30"
        assert "bogus" not in sent and "operation" not in sent


# ── état du tour précédent ──


class TestEtatPerime:
    @pytest.mark.asyncio
    async def test_consigne_de_clarif_effacee(self) -> None:
        eng, _ = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv")
        assert chat.state.clarification_instruction
        r = await chat.say("une coupe femme demain à 14h")
        assert (r.action_result or {}).get("success") is True
        assert chat.state.clarification_instruction is None

    @pytest.mark.asyncio
    async def test_lacune_pas_reportee(self) -> None:
        from jenny.engine.response_generator import ResponseGenerator

        seen: list[bool] = []

        class _Gen(ResponseGenerator):
            def __init__(self) -> None:
                pass

            async def generate(self, state, on_token=None) -> str:
                seen.append(state.knowledge_gap)
                return "Bonjour !"

        eng, _ = _engine(response_generator=_Gen())
        chat = _Chat(eng)
        await chat.say("Bonjour")
        chat.state.knowledge_gap = True  # tour d'avant
        await chat.say("Bonjour")
        assert seen == [False, False]

    @pytest.mark.asyncio
    async def test_au_revoir_oublie_les_manques(self) -> None:
        eng, _ = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv")
        assert chat.state.has_missing_required_slots()
        r = await chat.say("merci au revoir")
        assert r.intent == "closing"
        assert r.clarification_reason != "slot_filling"
        assert not chat.state.has_missing_required_slots()

    @pytest.mark.asyncio
    async def test_question_prix_garde_le_rdv(self) -> None:
        # B14 : reprise une seule fois
        eng, acts = _engine()
        chat = _Chat(eng)
        await chat.say("je veux un rdv pour une coupe femme")
        r = await chat.say("c'est combien ?")
        assert r.intent == "pricing"
        assert chat.state.pending_intent == "appointment"
        r = await chat.say("demain à 14h")
        assert r.intent == "appointment"
        assert len([c for c in acts["book"].calls if c.get("time")]) == 1


# ── seuils partagés ──


class TestSeuils:
    @pytest.mark.asyncio
    async def test_rag_meme_seuil(self) -> None:
        seen: list[float] = []

        class _Retriever:
            async def search(self, query, *, business_id, top_k, score_threshold):
                seen.append(score_threshold)
                return []

        eng, _ = _engine(retriever=_Retriever())
        await _Chat(eng).say("vous avez un parking ?")
        assert seen == [FAQ_MIN_SCORE]

    @pytest.mark.asyncio
    async def test_humain_sous_le_seuil_routeur(self) -> None:
        from ml.models.intent.predict import IntentPredictor

        class _Low(IntentPredictor):
            def __init__(self) -> None:
                pass

            def predict_multi(self, text: str) -> dict:
                hit = {"intent": "general", "confidence": 0.35}
                return {
                    "primary_intent": "general",
                    "primary_confidence": 0.35,
                    "intents": [hit],
                    "is_multi_intent": False,
                    "needs_clarification": True,
                }

        eng, _ = _engine(intent_predictor=_Low())
        r = await _Chat(eng).say("blablabla")
        # routeur < 0.4 → humain aussi
        assert r.requires_human is True


# ── débit : modèles hors boucle ──


class TestDebit:
    @pytest.mark.asyncio
    async def test_boucle_libre_pendant_inference(self) -> None:
        from ml.models.intent.predict import IntentPredictor
        from ml.models.ner.predict import NERPredictor

        class _SlowIntent(IntentPredictor):
            def __init__(self) -> None:
                pass

            def predict_multi(self, text: str) -> dict:
                _time.sleep(0.15)
                hit = {"intent": "faq", "confidence": 0.9}
                return {
                    "primary_intent": "faq",
                    "primary_confidence": 0.9,
                    "intents": [hit],
                    "is_multi_intent": False,
                    "needs_clarification": False,
                }

        class _SlowNER(NERPredictor):
            def __init__(self) -> None:
                pass

            def predict(self, text: str) -> dict[str, str]:
                _time.sleep(0.15)
                return {}

        eng, _ = _engine(intent_predictor=_SlowIntent(), ner_predictor=_SlowNER())
        ticks = 0
        done = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not done.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        r = await _Chat(eng).say("vous êtes ouverts le dimanche ?")
        done.set()
        await task
        assert r.intent == "faq"
        # ~0.3 s d'inférence, boucle vivante
        assert ticks >= 10
