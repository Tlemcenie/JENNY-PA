"""Moteur conversationnel principal de Jenny."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jenny.core.logging import get_logger
from jenny.engine.intelligence import (
    clean_question,
    decide_clarification,
    detect_language,
    extract_customer_facts,
    is_knowledge_gap,
    refine_knowledge_gap,
)
from jenny.engine.state_manager import ConversationPhase, ConversationState, StateManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    TokenCallback = Callable[[str], Awaitable[None]]

logger = get_logger(__name__)

# seuil de confiance ML
ML_CONFIDENCE_FLOOR = 0.5

# intentions de politesse
GREETING_INTENTS = frozenset({"greeting", "small_talk"})

# une info à la fois
# interrompt ou complète l'action
_INTERRUPTING_INTENTS = frozenset({"escalation", "complaint"})
_CONTINUABLE_INTENTS = frozenset(
    {"general", "greeting", "small_talk", "planning", "faq", "appointment", "closing"}
)
# demandes d'info à honorer
_INFO_REQUEST_INTENTS = frozenset({"pricing", "quote", "payment", "payment_question"})
_CLOSING_RE = re.compile(
    r"\b(merci|au\s*revoir|bonne\s+journ[ée]e|[àa]\s+bient[ôo]t|[àa]\s+plus|"
    r"au\s+plaisir|bye|ciao|c['’]est\s+(?:bon|tout|parfait|gentil))\b",  # noqa: RUF001
    re.I,
)

# gestion du rdv client
_MGMT_CANCEL_RE = re.compile(
    r"\b(annul|d[ée]command)|\bsupprim\w*\s+(?:mon|le)\s+(?:rdv|rendez)", re.I
)
_MGMT_RESCHED_RE = re.compile(
    r"\b(d[ée]plac|d[ée]cal|repouss)|\breport\w*\s+(?:mon|le)\s+(?:rdv|rendez)|"
    r"chang\w*\s+(?:l['’]?heure|de\s+jour|la\s+date)",  # noqa: RUF001
    re.I,
)
_MGMT_CONFIRM_RE = re.compile(
    r"\bje\s+confirme|c['’]est\s+confirm|je\s+valide|je\s+maintiens",  # noqa: RUF001
    re.I,
)
# question générique catalogue
_CATALOG_TOPIC_RE = re.compile(
    r"(?:vos|tes|les|des)\s+(?:prestations|tarifs|services|prix)\b|catalogue|grille\s+tarifaire",
    re.I,
)
# on veut la liste des prestations
_CATALOG_LIST_RE = re.compile(
    r"(?:vous|tu)\s+(?:faites|fais|proposez|propose|avez|offrez|faîtes)\s+quoi"
    r"|quoi\s+comme\s+(?:prestations?|services?|soins?|coupes?)"
    r"|qu['’]?est[- ]ce\s+que\s+(?:vous|tu)\s+(?:faites|proposez|avez|fais)"  # noqa: RUF001
    r"|quelles?\s+(?:sont\s+)?(?:vos|les)?\s*(?:prestations?|services?|soins?|options?)"
    r"|c['’]?est\s+quoi\s+(?:vos|les)\s+(?:prestations?|services?|tarifs?)"  # noqa: RUF001
    r"|(?:vos|tes|les)\s+(?:prestations?|services?)\b"
    r"|catalogue|grille\s+tarifaire|liste\s+(?:des\s+)?(?:prestations?|services?)",
    re.I,
)

_AFFIRM_RE = re.compile(
    r"^\s*(oui|ouais|ok|d['’]accord|c['’]est\s+(?:bon|parfait)|[çc]a\s+me\s+va|"  # noqa: RUF001
    r"carr[ée]ment|volontiers|parfait|nickel)\b",
    re.I,
)

# signaux de prise de rdv
_STRONG_APPOINTMENT_RE = re.compile(
    r"\b(rendez[\s-]?vous|rdv|r[ée]serv\w+|prendre\s+(?:un\s+)?(?:rendez|rdv|cr[ée]neau)|"
    r"booker|je\s+veux\s+(?:un\s+)?(?:rdv|rendez))\b",
    re.I,
)

# signal de devis
_STRONG_QUOTE_RE = re.compile(r"\b(devis|estimation|chiffrage|chiffrer)\b", re.I)
# signal de question de prix
_PRICE_SIGNAL_RE = re.compile(
    r"\b(combien|prix|tarif|tarifs|co[uû]te|co[uû]tent|co[uû]t|ça fait)\b", re.I
)

# signaux de réclamation
_COMPLAINT_SIGNAL_RE = re.compile(
    r"\b(d[ée]çu\w*|décevant|nul\w*|rat[ée]\w*|catastroph\w*|scandal\w*|honteu\w*|"
    r"inadmissible|inacceptable|rembours\w*|me\s+plain\w*|r[ée]clamation|mécontent\w*|"
    r"insatisfait\w*|jamais\s+content|horrible|lamentable|arnaqu\w*|abus\w*)\b",
    re.I,
)


# capture du nom
_NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\- ]{1,40}$")  # noqa: RUF001
# préfixes « c'est pour… », « je m'appelle… »
_NAME_INTRO_RE = re.compile(
    r"^\s*(?:c['’]est\s+pour|c['’]est\s+au\s+nom\s+de|c['’]est|moi\s+c['’]est|"  # noqa: RUF001
    r"je\s+m['’]appelle|au\s+nom\s+de|je\s+suis|mon\s+nom\s+(?:c['’]est|est))\s+",  # noqa: RUF001
    re.I,
)
# pas des noms
_NOT_A_NAME = frozenset(
    {"moi", "lui", "elle", "nous", "vous", "eux", "toi", "ça", "pour", "oui", "non", "ok"}
)


def looks_like_name(text: str) -> bool:
    """Ressemble à un nom ?"""
    t = (text or "").strip()
    if not t or "?" in t or any(ch.isdigit() for ch in t):
        return False
    t = _NAME_INTRO_RE.sub("", t).strip(" .!,")  # retire le préfixe
    if not t or t.lower() in _NOT_A_NAME:
        return False
    if _CLOSING_RE.search(t) or _GREETING_PREFIX_RE.match(t):
        return False
    words = t.split()
    return 1 <= len(words) <= 3 and bool(_NAME_RE.match(t))


def _norm_txt(s: str) -> str:
    """Minuscule sans accents."""
    import unicodedata

    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def match_catalog_services(message: str, services: list[str]) -> str | None:
    """Repère les prestations citées."""
    if not message or not services:
        return None
    m = _norm_txt(message)
    found = [svc for svc in services if (n := _norm_txt(svc)) and len(n) > 2 and n in m]
    return " et ".join(found) if found else None


def detect_appointment_mgmt(message: str, awaiting_confirmation: bool) -> str | None:
    """Le client gère son rdv ?"""
    m = message or ""
    if _MGMT_CANCEL_RE.search(m):
        return "cancel"
    if _MGMT_RESCHED_RE.search(m):
        return "reschedule"
    if _MGMT_CONFIRM_RE.search(m):
        return "confirm"
    if awaiting_confirmation and _AFFIRM_RE.search(m):
        return "confirm"
    return None


_SLOT_ASK_FR: dict[str, str] = {
    "service": (
        "Pour préparer le rendez-vous, demande au client QUELLE PRESTATION il "
        "souhaite (coupe, couleur, balayage, brushing…), chaleureusement et en une phrase."
    ),
    "date": "Demande au client POUR QUEL JOUR il aimerait son rendez-vous, simplement.",
    "time": "Demande au client À QUELLE HEURE l'arrangerait, simplement.",
    "order_number": "Demande au client son NUMÉRO DE COMMANDE pour pouvoir l'aider.",
}

# seuil d'override salutation
GREETING_OVERRIDE_FLOOR = 0.5

# salutations en tête de message
_GREETING_WORDS = (
    r"bonjour|bonsoir|bonne\s+journ[ée]e|bonne\s+soir[ée]e|salut|coucou|"
    r"hello|hey|hi|bjr|slt|yo|wesh|cc"
)
_GREETING_PREFIX_RE = re.compile(
    rf"^\s*\b(?:{_GREETING_WORDS})\b(?:[\s,;:!.…-]+\b(?:{_GREETING_WORDS})\b)*[\s,;:!.…-]*",
    re.IGNORECASE,
)

# remerciements en tête
_THANKS_WORDS = (
    r"merci(?:\s+beaucoup|\s+bien)?|super|parfait|top|g[ée]nial|nickel|"
    r"c['’]est\s+not[ée]|d['’]accord|ok(?:ay)?"  # noqa: RUF001
)
_THANKS_PREFIX_RE = re.compile(
    rf"^\s*\b(?:{_THANKS_WORDS})\b(?:[\s,;:!.…-]+\b(?:{_THANKS_WORDS})\b)*[\s,;:!.…-]*",
    re.IGNORECASE,
)


@dataclass
class EngineRequest:
    """Requête entrante vers le moteur."""

    conversation_id: UUID
    business_id: UUID
    message_text: str
    channel: str = ""
    customer_id: UUID | None = None
    language: str | None = None
    # persona du business
    persona: dict | None = None
    business_name: str | None = None
    # faits connus sur le client
    customer_facts: list[str] | None = None
    # catalogue formaté
    catalog: str | None = None
    # noms des prestations
    catalog_services: list[str] | None = None
    # horaires d'ouverture (texte)
    hours_text: str | None = None


@dataclass
class EngineResponse:
    """Réponse du moteur conversationnel."""

    response_text: str
    intent: str | None = None
    intent_confidence: float = 0.0
    detected_intents: list | None = None
    is_multi_intent: bool = False
    needs_clarification: bool = False
    clarification_reason: str = ""
    entities: dict[str, str] | None = None
    agent_used: str | None = None
    action_result: dict | None = None
    conversation_phase: str = ""
    requires_human: bool = False
    # signaux d'intelligence
    detected_language: str | None = None
    knowledge_gap: bool = False
    gap_question: str | None = None
    extracted_facts: list[dict] | None = None


class ConversationEngine:
    """Moteur conversationnel de Jenny."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        intent_predictor: object | None = None,
        ner_predictor: object | None = None,
        agent_router: object | None = None,
        response_generator: object | None = None,
        retriever: object | None = None,
    ) -> None:
        self.state_manager = state_manager or StateManager()
        self.intent_predictor = intent_predictor
        self.ner_predictor = ner_predictor
        self.agent_router = agent_router
        self.response_generator = response_generator
        # retriever RAG transverse
        self.retriever = retriever

    async def process(
        self, request: EngineRequest, on_token: TokenCallback | None = None
    ) -> EngineResponse:
        """Traite un message."""
        logger.info(
            "engine.process.start",
            conversation_id=str(request.conversation_id),
            channel=request.channel,
        )

        # 1. contexte
        state = self.state_manager.get_or_create(
            conversation_id=request.conversation_id,
            business_id=request.business_id,
            channel=request.channel,
        )
        state.add_user_message(request.message_text)
        state.language = request.language
        if request.customer_id is not None:
            state.customer_id = request.customer_id
        # persona du business
        if request.persona is not None:
            state.business_persona = request.persona
        if request.business_name is not None:
            state.business_name = request.business_name

        # langue du client
        state.detected_language = request.language or detect_language(request.message_text)
        # faits connus sur le client
        if request.customer_facts:
            state.customer_facts = list(request.customer_facts)
        # catalogue de prestations
        if request.catalog:
            state.business_catalog = request.catalog
        # horaires pour le prompt
        if request.hours_text:
            state.business_hours_text = request.hours_text

        # 2. intention
        intent_result = await self._detect_intent(request.message_text, state)

        # override rdv haute précision
        _msg_txt = request.message_text or ""
        _model_intent = intent_result["intent"]
        _blocks_appt_override = _model_intent in (
            "appointment",
            "manage_appointment",
            "escalation",
        ) or (_model_intent == "complaint" and _COMPLAINT_SIGNAL_RE.search(_msg_txt))
        # rdv sans mot-clé
        _has_when = False
        if not _blocks_appt_override:
            from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

            _has_when = bool(parse_fr_date(_msg_txt) or parse_fr_time(_msg_txt))
        _has_service = bool(
            request.catalog_services and match_catalog_services(_msg_txt, request.catalog_services)
        )
        _strong_appt = bool(_STRONG_APPOINTMENT_RE.search(_msg_txt))
        if (_strong_appt or (_has_when and _has_service)) and not _blocks_appt_override:
            logger.info(
                "engine.intent.appointment_override",
                was=intent_result["intent"],
                via="keyword" if _strong_appt else "service+when",
            )
            intent_result = {
                **intent_result,
                "intent": "appointment",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        # override devis
        if _STRONG_QUOTE_RE.search(request.message_text or "") and intent_result["intent"] not in (
            "appointment",
            "manage_appointment",
            "escalation",
            "complaint",
        ):
            logger.info("engine.intent.quote_override", was=intent_result["intent"])
            intent_result = {
                **intent_result,
                "intent": "quote",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        # prix + prestation → devis
        _price_signal = _PRICE_SIGNAL_RE.search(request.message_text or "")
        _cited_prestation = (
            match_catalog_services(request.message_text or "", request.catalog_services)
            if request.catalog_services
            else None
        )
        if (
            _cited_prestation
            and (intent_result["intent"] == "pricing" or _price_signal)
            and intent_result["intent"]
            not in ("appointment", "manage_appointment", "escalation", "complaint", "quote")
        ):
            logger.info(
                "engine.intent.pricing_to_quote",
                was=intent_result["intent"],
                prestation=_cited_prestation,
            )
            intent_result = {
                **intent_result,
                "intent": "quote",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        # catalogue générique → info groundée (pas small_talk / planning)
        if (
            _CATALOG_LIST_RE.search(request.message_text or "")
            and not _cited_prestation
            and not _has_when  # une vraie demande de créneau a une date
            and intent_result["intent"]
            not in (
                "appointment",
                "manage_appointment",
                "escalation",
                "complaint",
                "quote",
            )
        ):
            logger.info("engine.intent.catalog_to_faq", was=intent_result["intent"])
            intent_result = {
                **intent_result,
                "intent": "faq",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        intent = intent_result["intent"]
        intent_confidence = intent_result["confidence"]
        detected_intents = intent_result.get("detected_intents", [])
        is_multi_intent = intent_result.get("is_multi_intent", False)
        needs_clarification = intent_result.get("needs_clarification", False)

        # continuité de dialogue
        _resume_appointment_after_info = False
        if state.pending_intent and state.pending_intent != intent:
            from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

            msg_l = request.message_text or ""
            real_closing = intent == "closing" and bool(_CLOSING_RE.search(msg_l))
            hard_interrupt = intent in _INTERRUPTING_INTENTS or real_closing
            # complète une prise de rdv ?
            provides_appt_info = state.pending_intent == "appointment" and bool(
                parse_fr_date(msg_l) or parse_fr_time(msg_l)
            )
            # question d'info pendant un rdv
            info_interrupt = intent in _INFO_REQUEST_INTENTS and not provides_appt_info
            real_complaint = intent == "complaint" and bool(_COMPLAINT_SIGNAL_RE.search(msg_l))
            # mémorise l'interruption
            if info_interrupt and state.pending_intent == "appointment":
                _resume_appointment_after_info = True
            if provides_appt_info and not real_closing and not real_complaint:
                # jour/heure complète le rdv
                logger.info("engine.dialogue.resume_booking", read=intent)
                intent = state.pending_intent
                intent_confidence = max(intent_confidence, 0.7)
            elif (
                not hard_interrupt
                and not info_interrupt
                and (intent_confidence < 0.85 or intent in _CONTINUABLE_INTENTS)
            ):
                logger.info("engine.dialogue.continue", pending=state.pending_intent, read=intent)
                intent = state.pending_intent
                intent_confidence = max(intent_confidence, 0.6)

        # liste d'attente
        joining_waitlist = getattr(state, "awaiting_waitlist", False) and bool(
            _AFFIRM_RE.search(request.message_text or "")
        )
        state.awaiting_waitlist = False
        if joining_waitlist:
            intent = "join_waitlist"
            intent_confidence = 0.95
            state.pending_intent = None

        # gestion du rdv client
        mgmt_op = (
            None
            if joining_waitlist
            else detect_appointment_mgmt(
                request.message_text, getattr(state, "awaiting_confirmation", False)
            )
        )

        # report implicite sans mot-clé
        if mgmt_op is None and not joining_waitlist:
            _appt_slot = state.slots.get("appointment_id")
            if _appt_slot is not None and _appt_slot.filled:
                from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

                _m = request.message_text or ""
                _new_when = bool(parse_fr_date(_m) or parse_fr_time(_m))
                _new_service = bool(
                    request.catalog_services
                    and match_catalog_services(_m, request.catalog_services)
                )
                if _new_when and not _new_service and not looks_like_name(_m):
                    logger.info("engine.reschedule.implicit", appt="known")
                    mgmt_op = "reschedule"

        # capture du nom
        naming = (
            getattr(state, "awaiting_name", False)
            and not joining_waitlist
            and not mgmt_op
            and looks_like_name(request.message_text)
        )
        state.awaiting_name = False

        # capture du téléphone
        from jenny.actions.handlers.set_customer_phone import extract_phone

        _phone_in_msg = extract_phone(request.message_text)
        phoning = (
            getattr(state, "awaiting_phone", False)
            and not joining_waitlist
            and not mgmt_op
            and not naming
            and _phone_in_msg is not None
        )
        state.awaiting_phone = False
        if naming:
            intent = "set_customer_name"
            intent_confidence = 0.95
            state.pending_intent = None
            state.set_slot("name", request.message_text.strip())
        elif phoning:
            intent = "set_customer_phone"
            intent_confidence = 0.95
            state.pending_intent = None
            state.set_slot("phone", _phone_in_msg)
        elif mgmt_op:
            intent = "manage_appointment"
            intent_confidence = 0.9

        state.set_intent(intent, intent_confidence)

        if mgmt_op:
            state.set_slot("operation", mgmt_op)
            state.pending_intent = None

        # 3. entités
        entities = await self._extract_entities(request.message_text, state)
        for entity_name, entity_value in entities.items():
            state.set_slot(entity_name, entity_value)

        # capte dates/heures FR
        if intent in ("appointment", "manage_appointment"):
            from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

            msg = request.message_text.strip()
            if parse_fr_date(msg):
                state.set_slot("date", msg, entity_type="DATE")
            if parse_fr_time(msg):
                state.set_slot("time", msg, entity_type="TIME")
            # fallback prestation via catalogue
            svc_slot = state.slots.get("service")
            if not (svc_slot and svc_slot.filled) and request.catalog_services:
                matched_svc = match_catalog_services(msg, request.catalog_services)
                if not matched_svc:
                    # prestation citée avant
                    recent_user = " ".join(
                        m.get("content", "")
                        for m in state.message_history[-6:]
                        if m.get("role") == "user"
                    )
                    matched_svc = match_catalog_services(recent_user, request.catalog_services)
                if matched_svc:
                    state.set_slot("service", matched_svc, entity_type="SERVICE")

        # 4. agent
        state.phase = ConversationPhase.PROCESSING
        agent_result = await self._route_to_agent(state)
        state.agent_used = agent_result.get("agent", "fallback")
        state.action_result = agent_result.get("action_result")
        state.retrieved_documents = agent_result.get("documents", [])

        # grounding RAG transverse
        if (
            not state.retrieved_documents
            and self.retriever is not None
            and intent not in ("greeting", "closing", "escalation")
            and not (state.action_result or {}).get("success")
        ):
            try:
                # seuil sous le floor
                _hits = await self.retriever.search(
                    request.message_text,
                    business_id=state.business_id,
                    top_k=3,
                    score_threshold=0.35,
                )
                if _hits:
                    state.retrieved_documents = [
                        {"content": h.content, "score": h.score, "metadata": h.metadata}
                        for h in _hits
                    ]
                    logger.info(
                        "engine.rag_grounded",
                        results=len(_hits),
                        top_score=round(_hits[0].score, 3),
                    )
            except Exception as _e:  # pragma: no cover
                logger.warning("engine.rag_ground_failed", error=str(_e))

        # suivi de confirmation
        _ar = state.action_result or {}
        if _ar.get("success") and _ar.get("appointment_id") and not _ar.get("operation"):
            state.awaiting_confirmation = True
        elif _ar.get("operation") in {"confirm", "cancel"}:
            state.awaiting_confirmation = False

        # salon complet: liste d'attente
        if _ar.get("no_slots"):
            state.awaiting_waitlist = True
        # client sans nom
        if _ar.get("ask_name"):
            state.awaiting_name = True
        # retient l'id du rdv
        if _ar.get("appointment_id"):
            state.set_slot("appointment_id", str(_ar["appointment_id"]))
        # adopte l'id client
        if _ar.get("named") and _ar.get("customer_id"):
            try:
                from uuid import UUID as _UUID

                state.customer_id = _UUID(str(_ar["customer_id"]))
            except (ValueError, TypeError):
                pass
        if _ar.get("ask_phone"):
            state.awaiting_phone = True

        # slot-filling prioritaire
        clarification_reason = ""
        if state.has_missing_required_slots():
            missing = state.get_missing_slots()
            state.clarification_instruction = _SLOT_ASK_FR.get(
                missing[0].name,
                "Demande poliment au client l'information manquante pour traiter sa demande.",
            )
            needs_clarification = True
            clarification_reason = "slot_filling"
            # garde l'action en cours
            state.pending_intent = intent
        elif intent == "appointment" and not (state.action_result or {}).get("success"):
            # rdv en cours
            state.pending_intent = "appointment"
            needs_clarification = True
            clarification_reason = "booking_in_progress"
        elif intent == "manage_appointment" and not (state.action_result or {}).get("success"):
            # gestion rdv en cours
            state.pending_intent = "manage_appointment"
            needs_clarification = True
            clarification_reason = "booking_in_progress"
        elif _resume_appointment_after_info:
            # garde la réservation en attente
            state.pending_intent = "appointment"
        else:
            # action finie, on libère
            state.pending_intent = None
            # clarification générale
            decision = decide_clarification(
                message_text=request.message_text,
                intent=intent,
                confidence=intent_confidence,
                entities=entities,
                detected_intents=detected_intents,
                is_multi_intent=is_multi_intent,
            )
            if decision.needs_clarification or needs_clarification:
                needs_clarification = True
                clarification_reason = decision.reason or "ml_uncertain"
                state.clarification_instruction = decision.instruction or (
                    "Le message du client est ambigu : demande-lui poliment une "
                    "précision avant de répondre, sans deviner."
                )

        # réservation en attente prioritaire
        if _resume_appointment_after_info:
            state.pending_intent = "appointment"

        # lacune de connaissance
        gap = is_knowledge_gap(
            intent=intent,
            documents=state.retrieved_documents,
            action_result=state.action_result,
            message=request.message_text,
        )
        # catalogue = pas une lacune
        if (
            gap
            and state.business_catalog
            and (
                intent in ("pricing", "quote")
                or _CATALOG_TOPIC_RE.search(request.message_text or "")
            )
        ):
            gap = False
        gap_question: str | None = None
        # pas de lacune si clarification
        if gap and not needs_clarification:
            state.knowledge_gap = True
            gap_question = clean_question(request.message_text)

        # faits à mémoriser
        extracted_facts = extract_customer_facts(request.message_text)

        # 5. réponse LLM
        state.phase = ConversationPhase.RESPONDING
        response_text = await self._generate_response(state, on_token=on_token)

        # affine la lacune après génération
        from jenny.engine.intelligence import _retrieval_has_answer

        grounded = _retrieval_has_answer(state.retrieved_documents, request.message_text)
        final_gap = refine_knowledge_gap(
            intent=intent,
            response_text=response_text,
            action_result=state.action_result,
            pre_gap=gap,
            needs_clarification=needs_clarification,
            retrieval_grounded=grounded,
        )
        state.knowledge_gap = final_gap
        gap_question = clean_question(request.message_text) if final_gap else None

        # 6. maj de l'état
        state.suggested_response = response_text
        state.add_assistant_message(response_text)
        self.state_manager.save(state)

        logger.info(
            "engine.process.done",
            conversation_id=str(request.conversation_id),
            intent=intent,
            agent=state.agent_used,
            turn=state.turn_count,
        )

        return EngineResponse(
            response_text=response_text,
            intent=intent,
            intent_confidence=intent_confidence,
            detected_intents=detected_intents,
            is_multi_intent=is_multi_intent,
            needs_clarification=needs_clarification,
            clarification_reason=clarification_reason,
            entities=entities if entities else None,
            agent_used=state.agent_used,
            action_result=state.action_result,
            conversation_phase=state.phase.value,
            requires_human=intent == "escalation" or intent_confidence < 0.3,
            detected_language=state.detected_language,
            knowledge_gap=state.knowledge_gap,
            gap_question=gap_question,
            extracted_facts=extracted_facts or None,
        )

    async def _detect_intent(self, text: str, state: ConversationState) -> dict:
        """Détecte l'intention, politesse démasquée."""
        result = await self._classify_text(text)

        # démasque aussi les remerciements
        masked_intents = GREETING_INTENTS | {"closing"} if "?" in text else GREETING_INTENTS
        if result["intent"] in masked_intents:
            remainder = self._strip_leading_greeting(text) or self._strip_leading_thanks(text)
            if remainder:
                sub = await self._classify_text(remainder)
                if (
                    sub["intent"] not in masked_intents
                    and sub["confidence"] >= GREETING_OVERRIDE_FLOOR
                ):
                    logger.info(
                        "engine.intent.greeting_unmasked",
                        masked_by=result["intent"],
                        real_intent=sub["intent"],
                        confidence=round(sub["confidence"], 3),
                    )
                    # salutation en intention secondaire
                    sub["detected_intents"] = [
                        *sub["detected_intents"],
                        {"intent": result["intent"], "confidence": result["confidence"]},
                    ]
                    sub["is_multi_intent"] = True
                    sub["was_greeting"] = True
                    return sub

        return result

    async def _classify_text(self, text: str) -> dict:
        """Classifie un texte en intention."""
        if self.intent_predictor is not None:
            try:
                from ml.models.intent.predict import IntentPredictor

                if isinstance(self.intent_predictor, IntentPredictor):
                    result = self.intent_predictor.predict_multi(text)
                    ml_intent = result["primary_intent"]
                    ml_conf = result["primary_confidence"]

                    if ml_conf < ML_CONFIDENCE_FLOOR:
                        rule_intent, rule_conf = self._rule_based_intent(text)
                        if rule_intent != "general" and rule_conf > ml_conf:
                            return {
                                "intent": rule_intent,
                                "confidence": rule_conf,
                                "detected_intents": [
                                    {"intent": rule_intent, "confidence": rule_conf}
                                ],
                                "is_multi_intent": False,
                                "needs_clarification": False,
                            }

                    return {
                        "intent": ml_intent,
                        "confidence": ml_conf,
                        "detected_intents": result["intents"],
                        "is_multi_intent": result["is_multi_intent"],
                        "needs_clarification": result["needs_clarification"],
                    }
            except (ImportError, Exception) as e:
                logger.warning("engine.intent.model_error", error=str(e))

        # fallback: règles mots-clés
        intent, confidence = self._rule_based_intent(text)
        return {
            "intent": intent,
            "confidence": confidence,
            "detected_intents": [{"intent": intent, "confidence": confidence}],
            "is_multi_intent": False,
            "needs_clarification": False,
        }

    def _strip_leading_greeting(self, text: str) -> str:
        """Retire la salutation en tête."""
        remainder = _GREETING_PREFIX_RE.sub("", text, count=1).strip()
        if not remainder or remainder == text.strip():
            return ""
        if len(re.findall(r"\w+", remainder)) < 2:
            return ""
        return remainder

    def _strip_leading_thanks(self, text: str) -> str:
        """Retire le remerciement en tête."""
        remainder = _THANKS_PREFIX_RE.sub("", text, count=1).strip()
        if not remainder or remainder == text.strip():
            return ""
        if len(re.findall(r"\w+", remainder)) < 2:
            return ""
        return remainder

    def _rule_based_intent(self, text: str) -> tuple[str, float]:
        """Intention par règles (fallback)."""
        text_lower = text.lower()

        rules: list[tuple[list[str], str]] = [
            (["bonjour", "salut", "hello", "hey", "bonsoir"], "greeting"),
            (["commande", "colis", "livraison", "suivi", "tracking"], "order_status"),
            (["prix", "tarif", "coût", "combien"], "pricing"),
            (["rendez-vous", "rdv", "réserver"], "appointment"),
            (["problème", "bug", "erreur", "marche pas", "défaut", "plainte"], "complaint"),
            (["aide", "comment", "pourquoi", "expliquer"], "faq"),
            (["merci", "au revoir", "bonne journée", "à bientôt"], "closing"),
            (["humain", "conseiller", "parler à quelqu'un"], "escalation"),
            (["payer", "paiement", "régler", "facture", "virement"], "payment"),
            (["devis", "estimation", "chiffrage"], "quote"),
            (["planning", "disponibilité", "créneau", "calendrier", "horaire"], "planning"),
        ]

        for keywords, intent in rules:
            if any(kw in text_lower for kw in keywords):
                return intent, 0.75

        return "general", 0.5

    async def _extract_entities(self, text: str, state: ConversationState) -> dict[str, str]:
        """Extrait les entités du message."""
        if self.ner_predictor is not None:
            try:
                from ml.models.ner.predict import NERPredictor

                if isinstance(self.ner_predictor, NERPredictor):
                    return self.ner_predictor.predict(text)
            except (ImportError, Exception) as e:
                logger.warning("engine.ner.model_error", error=str(e))

        return self._regex_entity_extraction(text)

    def _regex_entity_extraction(self, text: str) -> dict[str, str]:
        """Extraction d'entités par regex (fallback)."""
        entities: dict[str, str] = {}

        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            entities["email"] = email_match.group()

        phone_match = re.search(r"(?:\+33|0)\s*[1-9](?:[\s.-]*\d{2}){4}", text)
        if phone_match:
            entities["phone"] = phone_match.group()

        order_match = re.search(
            r"(?:commande|cmd|order)\s*[#:]?\s*([A-Z0-9-]{4,20})", text, re.IGNORECASE
        )
        if order_match:
            entities["order_number"] = order_match.group(1)

        date_match = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text)
        if date_match:
            entities["date"] = date_match.group()

        amount_match = re.search(r"(\d+(?:[.,]\d{2})?)\s*€", text)
        if amount_match:
            entities["amount"] = amount_match.group(1)

        return entities

    async def _route_to_agent(self, state: ConversationState) -> dict:
        """Route vers le bon agent."""
        if self.agent_router is not None:
            try:
                from jenny.agents.router import AgentRouter

                if isinstance(self.agent_router, AgentRouter):
                    return await self.agent_router.route(state)
            except (ImportError, Exception) as e:
                logger.warning("engine.router.error", error=str(e))

        return {"agent": "fallback", "documents": [], "action_result": None}

    async def _generate_response(
        self, state: ConversationState, on_token: TokenCallback | None = None
    ) -> str:
        """Génère la réponse LLM."""
        if self.response_generator is not None:
            try:
                from jenny.engine.response_generator import ResponseGenerator

                if isinstance(self.response_generator, ResponseGenerator):
                    return await self.response_generator.generate(state, on_token=on_token)
            except (ImportError, Exception) as e:
                logger.warning("engine.generator.error", error=str(e))

        # fallback si pas de LLM
        return self._template_response(state)

    def _template_response(self, state: ConversationState) -> str:
        """Réponses templates (fallback sans LLM)."""
        templates: dict[str, str] = {
            "greeting": "Bonjour ! Comment puis-je vous aider aujourd'hui ?",
            "small_talk": "Ça va bien merci ! 😊 Comment puis-je vous aider ?",
            "order_status": "Je vais vérifier le statut de votre commande.",
            "pricing": "Je vais vous communiquer nos tarifs.",
            "appointment": "Je vais vérifier les créneaux disponibles.",
            "complaint": "Je suis désolé pour ce désagrément. Je prends note de votre retour.",
            "faq": "Laissez-moi chercher cette information pour vous.",
            "closing": "Merci pour votre message ! N'hésitez pas à revenir. Bonne journée !",
            "escalation": "Je vous transfère vers un conseiller. Un instant s'il vous plaît.",
            "payment": "Je vais vous aider avec votre paiement.",
            "payment_question": "Nous acceptons la carte bancaire, les espèces et les virements.",
            "quote": "Je prépare votre demande de devis.",
            "planning": "Je consulte les disponibilités pour vous.",
        }
        return templates.get(
            state.current_intent or "general",
            "Merci pour votre message. Je vais traiter votre demande.",
        )
