"""passe 3 moteur : ReDoS, offre, garde, oubli."""

from __future__ import annotations

import time
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
    _FAREWELL_WHEN_RE,
    ConversationEngine,
    EngineRequest,
    clip_rules_text,
    extract_customer_name,
    is_farewell,
    is_implicit_reschedule,
    offered_slots,
    picks_offered_slot,
    strip_farewell,
)
from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time
from jenny.engine.response_generator import strip_filler_phrases, strip_letter_format
from jenny.engine.state_manager import ConversationState, StateManager
from jenny.engine.thresholds import RULES_MAX_CHARS

LUNDI = date(2026, 10, 26)
CATALOG = ["Coupe femme", "Coupe homme", "Balayage"]
BUDGET = 0.05  # 50 ms


def _fast(fn, *args, **kw) -> float:
    """meilleur temps sur 3 essais"""
    best = 9.0
    for _ in range(3):
        t0 = time.perf_counter()
        fn(*args, **kw)
        best = min(best, time.perf_counter() - t0)
        if best < BUDGET:
            break
    return best


# ── ReDoS au revoir ──


_ATTAQUES = [
    "merci, à demain" + " merci encore" * 40 + " ?",
    "merci, à demain" + " encore merci" * 40 + "x",
    "à demain" + ", merci à vous" * 40 + " rdv",
    "à jeudi 10h" + " encore merci encore" * 40 + " ?",
    "merci, à demain" + " merci encore" * 600 + " ?",
    "bisous à demain" + " et encore merci beaucoup" * 300 + " ?",
]


class TestRedosAuRevoir:
    @pytest.mark.parametrize("msg", _ATTAQUES)
    def test_fonctions_rapides(self, msg: str) -> None:
        assert _fast(_FAREWELL_WHEN_RE.search, msg) < BUDGET
        assert _fast(strip_farewell, msg) < BUDGET
        assert _fast(is_farewell, msg, today=LUNDI) < BUDGET
        kw = {"today": LUNDI, "services": CATALOG, "booked": ("2026-10-30", "10:00")}
        assert _fast(is_implicit_reschedule, msg, **kw) < BUDGET

    def test_meme_resultat(self) -> None:
        # le sens ne change pas
        assert is_farewell("merci, à demain merci encore merci", today=LUNDI)
        assert is_farewell("à demain encore merci encore", today=LUNDI)
        assert not is_farewell("merci, à demain merci encore ?", today=LUNDI)
        assert not is_farewell("à demain merci encore rdv", today=LUNDI)

    def test_nom_et_signature_rapides(self) -> None:
        assert _fast(extract_customer_name, "Marie" + " " * 5000 + "@", CATALOG) < BUDGET
        assert _fast(strip_letter_format, "Bonjour" + "\n" * 5000 + "@") < BUDGET
        assert _fast(strip_filler_phrases, "Super." + "\n" * 5000 + "?") < BUDGET
        # comportement gardé
        assert strip_letter_format("Merci pour tout !\n\nCordialement,\nJenny") == (
            "Merci pour tout !"
        )
        assert extract_customer_name("Marie   et Paul", CATALOG) == "Marie"


# ── texte borné ──


class TestTexteBorne:
    def test_clip(self) -> None:
        assert clip_rules_text(None) == ""
        assert len(clip_rules_text("a" * 9000)) == RULES_MAX_CHARS
        assert clip_rules_text("jeudi 10h") == "jeudi 10h"

    def test_dates_au_dela_ignorees(self) -> None:
        long = "x" * (RULES_MAX_CHARS + 10) + " jeudi 10h"
        assert parse_fr_date(long, today=LUNDI) is None
        assert parse_fr_time(long) is None
        assert parse_fr_date("bla " * 10 + "jeudi", today=LUNDI) == date(2026, 10, 29)


# ── créneaux proposés ──


class TestOffre:
    def test_libelles_du_salon(self) -> None:
        got = offered_slots("jeudi 29/10 à 10h00, vendredi 30/10 à 14h30", today=LUNDI)
        assert got == {("2026-10-29", "10:00"), ("2026-10-30", "14:30")}
        same = offered_slots("10h00, 11h15", today=LUNDI, day="2026-10-27")
        assert same == {("2026-10-27", "10:00"), ("2026-10-27", "11:15")}
        assert offered_slots(None, today=LUNDI) == set()

    @pytest.mark.parametrize(
        ("msg", "ok"),
        [
            ("Parfait, à vendredi 14h30 alors !", True),
            ("Merci, à jeudi 10h alors !", True),
            # refus poli
            ("Ok tant pis, merci, à jeudi 10h alors !", False),
            ("Non merci, à jeudi 10h alors !", False),
            # jour seul : ambigu
            ("Merci, à jeudi alors !", False),
            # pas proposé
            ("Merci, à jeudi 16h alors !", False),
        ],
    )
    def test_alternatives(self, msg: str, ok: bool) -> None:
        offer = {"alternatives_text": "jeudi 29/10 à 10h00, vendredi 30/10 à 14h30"}
        assert picks_offered_slot(msg, today=LUNDI, offer=offer) is ok

    def test_son_rdv_actuel(self) -> None:
        # même créneau que son rdv
        offer = {"alternatives_text": "jeudi 29/10 à 10h00"}
        kw = {"today": LUNDI, "offer": offer, "booked": ("2026-10-29", "10:00")}
        assert not picks_offered_slot("Merci, à jeudi 10h alors !", **kw)

    def test_propositions_du_jour(self) -> None:
        offer = {"propose_slots": True, "slots_text": "09h00, 09h45, 10h30"}
        kw = {"today": LUNDI, "offer": offer, "asked_day": "2026-10-27"}
        # heure libre du jour demandé
        assert picks_offered_slot("Parfait, à demain 11h alors !", **kw)
        assert not picks_offered_slot("Parfait, à jeudi 11h alors !", **kw)
        assert not picks_offered_slot("Non merci, à demain 11h alors !", **kw)


# ── garde sans opération ──


class _Act(BaseAction):
    required_params: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        return {"success": True, "appointment_id": "rdv-1"}


class _Book(_Act):
    name = "book_appointment"


class _Manage(_Act):
    name = "manage_appointment"

    async def execute(self, params: dict) -> dict:
        self.calls.append(dict(params))
        return {"success": True, "operation": params.get("operation") or "cancel"}


class _Fixed:
    """modèle qui dit toujours pareil"""

    def __init__(self, intent: str) -> None:
        self.intent = intent

    def predict_multi(self, text: str) -> dict:
        hit = {"intent": self.intent, "confidence": 0.92}
        return {"primary_intent": self.intent, "primary_confidence": 0.92, "intents": [hit]}


def _engine(**kw):
    reg = ActionRegistry()
    acts = {"book": _Book(), "manage": _Manage()}
    reg.register(acts["book"], intents=["appointment"])
    reg.register(acts["manage"], intents=["manage_appointment"])
    router = AgentRouter()
    router.register("action", ActionAgent(action_registry=reg))
    router.register("fallback", FallbackAgent())
    sm = StateManager(redis_url="redis://localhost:1/0")
    return ConversationEngine(state_manager=sm, agent_router=router, **kw), acts


async def _say(eng: ConversationEngine, conv, msg: str):
    return await eng.process(
        EngineRequest(
            conversation_id=conv, business_id=uuid4(), message_text=msg, catalog_services=CATALOG
        )
    )


class TestGardeOperation:
    @pytest.mark.asyncio
    async def test_pas_d_annulation_par_defaut(self) -> None:
        # modèle qui sort manage_appointment
        eng, acts = _engine()
        conv = uuid4()
        await _say(eng, conv, "je réserve une coupe femme demain à 10h")
        eng.intent_predictor = _Fixed("manage_appointment")
        r = await _say(eng, conv, "ok super")
        assert acts["manage"].calls == []
        assert r.intent != "manage_appointment"

    @pytest.mark.asyncio
    async def test_vrai_report_passe(self) -> None:
        eng, acts = _engine()
        conv = uuid4()
        await _say(eng, conv, "je réserve une coupe femme demain à 10h")
        r = await _say(eng, conv, "je voudrais décaler à jeudi 15h")
        assert r.intent == "manage_appointment"
        assert acts["manage"].calls[-1]["operation"] == "reschedule"

    @pytest.mark.asyncio
    async def test_long_message_moteur_rapide(self) -> None:
        # message géant : pas de gel
        eng, _ = _engine()
        conv = uuid4()
        for msg in (
            "merci, à demain" + " merci encore" * 400 + " ?",
            "1" * 5000,
            "commande" + " " * 5000 + "!",
            "Marie" + " " * 5000 + "@",
        ):
            t0 = time.perf_counter()
            await _say(eng, conv, msg)
            assert time.perf_counter() - t0 < 1.0


# ── oubli mémoire ──


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str):
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


class TestForget:
    def test_oublie_la_memoire_seule(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0")
        sm._redis = _FakeRedis()
        st = ConversationState(conversation_id=uuid4())
        st.booked_date = "2026-10-29"
        sm.save(st)
        key = sm._key(str(st.conversation_id))
        assert sm.forget(st.conversation_id) is True
        assert len(sm._states) == 0
        # Redis garde la copie
        assert key in sm._redis.data
        back = sm.get(st.conversation_id)
        assert back is not None and back.booked_date == "2026-10-29"
        assert sm.forget(uuid4()) is False

    @pytest.mark.asyncio
    async def test_sans_redis_etat_perdu(self) -> None:
        sm = StateManager(redis_url="redis://localhost:1/0")
        st = await sm.aget_or_create(uuid4())
        await sm.asave(st)
        assert sm.forget(st.conversation_id) is True
        assert await sm.aget(st.conversation_id) is None
