"""Moteur conversationnel principal de Jenny.

C'est le chef d'orchestre du traitement. Pour chaque message entrant :
1. Récupérer le contexte (StateManager)
2. Détecter l'intention (modèle Intent)
3. Extraire les entités (modèle NER)
4. Router vers le bon agent (AgentRouter)
5. Générer la réponse via LLM (ResponseGenerator)
6. Mettre à jour l'état
7. Retourner la réponse

TOUTES les réponses passent par le LLM pour un ton naturel.
Les agents exécutent les actions, le LLM formule la réponse.
"""

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

# En dessous de ce seuil, une prédiction d'intention ML est jugée trop
# incertaine pour écraser un match mot-clé franc des règles déterministes.
ML_CONFIDENCE_FLOOR = 0.5

# Intentions « conversationnelles » (politesse). Quand elles ouvrent un message
# ("Bonjour, je veux un devis"), le modèle les sur-classe à ~1.0 et écrase la
# vraie demande : on les traite à part pour ne pas masquer l'intention utile.
GREETING_INTENTS = frozenset({"greeting", "small_talk"})

# Slot-filling : comment Jenny demande chaque info manquante (cas coiffeur).
# Une seule info à la fois, chaleureusement.
# Continuité de dialogue : intentions qui interrompent franchement une action en
# cours, vs celles qui la complètent. Un « closing » n'interrompt que s'il contient
# de VRAIS mots de clôture (« merci », « au revoir ») — sinon c'est souvent un
# fragment de RDV (« mardi », « à 14h ») mal classé par le petit modèle.
_INTERRUPTING_INTENTS = frozenset({"escalation", "complaint"})
_CONTINUABLE_INTENTS = frozenset(
    {"general", "greeting", "small_talk", "planning", "faq", "appointment", "closing"}
)
# Demandes d'information à honorer même au milieu d'une prise de RDV (on répond au
# prix/devis/paiement plutôt que de happer le message dans le slot-filling).
_INFO_REQUEST_INTENTS = frozenset({"pricing", "quote", "payment", "payment_question"})
_CLOSING_RE = re.compile(
    r"\b(merci|au\s*revoir|bonne\s+journ[ée]e|[àa]\s+bient[ôo]t|[àa]\s+plus|"
    r"au\s+plaisir|bye|ciao|c['’]est\s+(?:bon|tout|parfait|gentil))\b",  # noqa: RUF001
    re.I,
)

# ── Gestion par le CLIENT de son propre RDV (annuler / déplacer / confirmer) ──
_MGMT_CANCEL_RE = re.compile(
    r"\b(annul|d[ée]command)|\bsupprim\w*\s+(?:mon|le)\s+(?:rdv|rendez)", re.I
)
_MGMT_RESCHED_RE = re.compile(
    r"\b(d[ée]plac|d[ée]cal|repouss)|\breport\w*\s+(?:mon|le)\s+(?:rdv|rendez)|"
    r"chang\w*\s+(?:l['’]?heure|de\s+jour|la\s+date)",  # noqa: RUF001
    re.I,
)
_MGMT_CONFIRM_RE = re.compile(
    r"\bje\s+confirme|c['’]est\s+confirm|je\s+valide|je\s+maintiens", re.I  # noqa: RUF001
)
_AFFIRM_RE = re.compile(
    r"^\s*(oui|ouais|ok|d['’]accord|c['’]est\s+(?:bon|parfait)|[çc]a\s+me\s+va|"  # noqa: RUF001
    r"carr[ée]ment|volontiers|parfait|nickel)\b",
    re.I,
)

# Signaux de PRISE de RDV non ambigus. Le petit modèle d'intention (qwen-class)
# classe souvent mal ces tournures FR (« réserver une coupe demain » → greeting
# 0.96 !), donc on force « appointment » par règle haute précision, quelle que soit
# la confiance ML. La gestion (annuler/déplacer) reste prioritaire et bascule
# ensuite vers manage_appointment (cf. detect_appointment_mgmt).
_STRONG_APPOINTMENT_RE = re.compile(
    r"\b(rendez[\s-]?vous|rdv|r[ée]serv\w+|prendre\s+(?:un\s+)?(?:rendez|rdv|cr[ée]neau)|"
    r"booker|je\s+veux\s+(?:un\s+)?(?:rdv|rendez))\b",
    re.I,
)

# Signal de DEVIS explicite : force « quote » → un VRAI devis persisté/envoyé,
# même si le petit modèle classe le message en « faq/pricing ».
_STRONG_QUOTE_RE = re.compile(r"\b(devis|estimation|chiffrage|chiffrer)\b", re.I)


# Capture du nom : un message qui ressemble à un nom propre (pas une commande,
# pas une question, pas un numéro) quand Jenny vient de demander « c'est à quel nom ? ».
_NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\- ]{1,40}$")  # noqa: RUF001


def looks_like_name(text: str) -> bool:
    """Vrai si le message ressemble à un nom (1-3 mots, lettres, sans « ? » ni chiffre)."""
    t = (text or "").strip()
    if not t or "?" in t or any(ch.isdigit() for ch in t):
        return False
    if _CLOSING_RE.search(t) or _GREETING_PREFIX_RE.match(t):
        return False
    words = t.split()
    return 1 <= len(words) <= 3 and bool(_NAME_RE.match(t))


def _norm_txt(s: str) -> str:
    """Minuscule sans accents (pour matcher une prestation dans un message)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def match_catalog_services(message: str, services: list[str]) -> str | None:
    """Repère les prestations du catalogue citées dans le message (NER-indépendant).

    « je veux une coupe et une couleur » + [Coupe, Couleur] → « Coupe et Couleur »
    (l'action de réservation re-découpe sur « et » pour gérer le multi-prestations).
    Renvoie None si rien trouvé.
    """
    if not message or not services:
        return None
    m = _norm_txt(message)
    found = [svc for svc in services if (n := _norm_txt(svc)) and len(n) > 2 and n in m]
    return " et ".join(found) if found else None


def detect_appointment_mgmt(message: str, awaiting_confirmation: bool) -> str | None:
    """Le client veut-il gérer SON rdv ? → cancel | reschedule | confirm | None."""
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

# Au-dessus de ce seuil, l'intention trouvée APRÈS avoir retiré la salutation
# prime sur la salutation elle-même.
GREETING_OVERRIDE_FLOOR = 0.5

# Salutations retirées en tête de message avant reclassement. Bornées par \b
# pour éviter les faux positifs ("rebonjour", "himalaya"...).
_GREETING_WORDS = (
    r"bonjour|bonsoir|bonne\s+journ[ée]e|bonne\s+soir[ée]e|salut|coucou|"
    r"hello|hey|hi|bjr|slt|yo|wesh|cc"
)
_GREETING_PREFIX_RE = re.compile(
    rf"^\s*\b(?:{_GREETING_WORDS})\b(?:[\s,;:!.…-]+\b(?:{_GREETING_WORDS})\b)*[\s,;:!.…-]*",
    re.IGNORECASE,
)


@dataclass
class EngineRequest:
    """Requête entrante vers le moteur conversationnel."""

    conversation_id: UUID
    business_id: UUID
    message_text: str
    channel: str = ""
    customer_id: UUID | None = None
    language: str | None = None
    # Cerveau de Jenny : persona configurable (ton, règles, vocabulaire) + nom du business.
    persona: dict | None = None
    business_name: str | None = None
    # Faits durables déjà connus sur le client (chargés depuis la DB par la route).
    customer_facts: list[str] | None = None
    # Catalogue de prestations formaté (prix/durée réels) — pour des réponses fondées.
    catalog: str | None = None
    # Noms des prestations (liste) — pour capter la prestation dans le message même
    # si le modèle NER est indisponible (réservation robuste, sans dépendre du ML).
    catalog_services: list[str] | None = None


@dataclass
class EngineResponse:
    """Réponse produite par le moteur conversationnel."""

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
    # ── Signaux de la couche d'intelligence (consommés par la route) ──
    detected_language: str | None = None
    knowledge_gap: bool = False
    gap_question: str | None = None
    extracted_facts: list[dict] | None = None


class ConversationEngine:
    """Moteur conversationnel central de Jenny.

    Orchestre le flux complet de traitement d'un message :
    contexte → intention → entités → agent → LLM → réponse.

    TOUTES les réponses passent par le LLM si disponible.
    """

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
        # Retriever RAG transverse : permet de chercher dans la base de connaissances
        # pour TOUTE question informative, même quand l'agent retenu n'est pas FAQ.
        self.retriever = retriever

    async def process(
        self, request: EngineRequest, on_token: TokenCallback | None = None
    ) -> EngineResponse:
        """Traite un message et produit une réponse.

        Flux complet :
        1. Contexte → 2. Intent → 3. NER → 4. Agent (action) → 5. LLM (réponse)

        ``on_token`` (optionnel) reçoit chaque token de la réponse LLM au fil de
        l'eau (chat en streaming). ``EngineResponse.response_text`` reste la
        version finale nettoyée.
        """
        logger.info(
            "engine.process.start",
            conversation_id=str(request.conversation_id),
            channel=request.channel,
        )

        # ── 1. Récupérer le contexte ──
        state = self.state_manager.get_or_create(
            conversation_id=request.conversation_id,
            business_id=request.business_id,
            channel=request.channel,
        )
        state.add_user_message(request.message_text)
        state.language = request.language
        if request.customer_id is not None:
            state.customer_id = request.customer_id
        # Cerveau de Jenny : persona du business → adapte ton/règles/vocabulaire.
        if request.persona is not None:
            state.business_persona = request.persona
        if request.business_name is not None:
            state.business_name = request.business_name

        # Langue : détectée si non fournie, pour répondre dans la langue du client.
        state.detected_language = request.language or detect_language(request.message_text)
        # Faits durables déjà connus sur ce client → personnalisation du contexte.
        if request.customer_facts:
            state.customer_facts = list(request.customer_facts)
        # Catalogue de prestations → prix/durée exacts pour les réponses de Jenny.
        if request.catalog:
            state.business_catalog = request.catalog

        # ── 2. Détecter l'intention (multi-label) ──
        intent_result = await self._detect_intent(request.message_text, state)

        # Override haute précision : un signal de RDV explicite (« rendez-vous »,
        # « réserver », « rdv ») force « appointment » même si le petit modèle est
        # (sur)confiant sur autre chose. Indispensable pour un app coiffeur : la
        # prise de RDV est le cœur du métier et le modèle s'y trompe souvent.
        if _STRONG_APPOINTMENT_RE.search(request.message_text or "") and intent_result[
            "intent"
        ] not in ("appointment", "manage_appointment", "escalation", "complaint"):
            logger.info(
                "engine.intent.appointment_override", was=intent_result["intent"]
            )
            intent_result = {
                **intent_result,
                "intent": "appointment",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        # Override : « devis »/« estimation »/« chiffrage » → quote (devis réel),
        # sauf si c'est déjà une prise de RDV / réclamation / escalade.
        if _STRONG_QUOTE_RE.search(request.message_text or "") and intent_result[
            "intent"
        ] not in ("appointment", "manage_appointment", "escalation", "complaint"):
            logger.info("engine.intent.quote_override", was=intent_result["intent"])
            intent_result = {
                **intent_result,
                "intent": "quote",
                "confidence": max(intent_result.get("confidence", 0.0), 0.85),
                "needs_clarification": False,
            }

        intent = intent_result["intent"]
        intent_confidence = intent_result["confidence"]
        detected_intents = intent_result.get("detected_intents", [])
        is_multi_intent = intent_result.get("is_multi_intent", False)
        needs_clarification = intent_result.get("needs_clarification", False)

        # ── Continuité de dialogue (slot-filling multi-tours) ──
        # Si une action attendait des infos, on garde SON intention tant que le
        # client ne change pas franchement de sujet : « mardi », « à 14h »…
        # complètent la prise de RDV même si le modèle les lit « closing »/« general ».
        if state.pending_intent and state.pending_intent != intent:
            from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

            msg_l = request.message_text or ""
            real_closing = intent == "closing" and bool(_CLOSING_RE.search(msg_l))
            hard_interrupt = intent in _INTERRUPTING_INTENTS or real_closing
            # Le message complète-t-il une prise de RDV (donne un jour/une heure) ?
            provides_appt_info = state.pending_intent == "appointment" and bool(
                parse_fr_date(msg_l) or parse_fr_time(msg_l)
            )
            # Une question d'INFO (prix, devis, paiement) au milieu d'une prise de RDV
            # mérite une vraie réponse : on ne la « happe » pas dans le slot-filling
            # (sauf si elle apporte aussi un jour/une heure). La prise de RDV reste
            # en attente (pending_intent) et pourra reprendre au message suivant.
            info_interrupt = intent in _INFO_REQUEST_INTENTS and not provides_appt_info
            if not hard_interrupt and not info_interrupt and (
                provides_appt_info
                or intent_confidence < 0.85
                or intent in _CONTINUABLE_INTENTS
            ):
                logger.info(
                    "engine.dialogue.continue", pending=state.pending_intent, read=intent
                )
                intent = state.pending_intent
                intent_confidence = max(intent_confidence, 0.6)

        # ── Liste d'attente : Jenny a proposé l'inscription (salon complet) ──
        # Offre à usage unique, consommée au tour suivant : un « oui » INSCRIT le
        # client ; toute autre réponse la laisse expirer (et peut relancer un RDV,
        # ex. si le client propose un autre jour). On la ré-arme plus bas si le salon
        # est encore complet à ce tour.
        joining_waitlist = getattr(state, "awaiting_waitlist", False) and bool(
            _AFFIRM_RE.search(request.message_text or "")
        )
        state.awaiting_waitlist = False
        if joining_waitlist:
            intent = "join_waitlist"
            intent_confidence = 0.95
            state.pending_intent = None

        # ── Gestion du RDV par le client (annuler / déplacer / confirmer) ──
        # Prioritaire sur la classification du modèle : un « annuler mon rdv » ne
        # doit pas être lu comme une nouvelle prise de RDV.
        mgmt_op = (
            None
            if joining_waitlist
            else detect_appointment_mgmt(
                request.message_text, getattr(state, "awaiting_confirmation", False)
            )
        )

        # ── Capture du nom : Jenny vient de demander « c'est à quel nom ? » ──
        # Le prochain message est alors le nom du client (sauf commande explicite).
        naming = (
            getattr(state, "awaiting_name", False)
            and not joining_waitlist
            and not mgmt_op
            and looks_like_name(request.message_text)
        )
        state.awaiting_name = False
        if naming:
            intent = "set_customer_name"
            intent_confidence = 0.95
            state.pending_intent = None
            state.set_slot("name", request.message_text.strip())
        elif mgmt_op:
            intent = "manage_appointment"
            intent_confidence = 0.9

        state.set_intent(intent, intent_confidence)

        if mgmt_op:
            state.set_slot("operation", mgmt_op)
            state.pending_intent = None

        # ── 3. Extraire les entités ──
        entities = await self._extract_entities(request.message_text, state)
        for entity_name, entity_value in entities.items():
            state.set_slot(entity_name, entity_value)

        # Renfort RDV : capter dates/heures en français (« mardi », « à 14h »).
        # On stocke le MESSAGE entier dès qu'il contient une date/heure analysable
        # (plus fiable qu'un fragment NER que combine_fr pourrait mal relire).
        if intent in ("appointment", "manage_appointment"):
            from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time

            msg = request.message_text.strip()
            if parse_fr_date(msg):
                state.set_slot("date", msg, entity_type="DATE")
            if parse_fr_time(msg):
                state.set_slot("time", msg, entity_type="TIME")
            # Fallback prestation : si le NER n'a pas rempli « service », on cherche
            # la prestation dans le catalogue du salon. La réservation ne dépend
            # alors PLUS du modèle ML (robuste même si le NER est indisponible).
            svc_slot = state.slots.get("service")
            if not (svc_slot and svc_slot.filled) and request.catalog_services:
                matched_svc = match_catalog_services(msg, request.catalog_services)
                if not matched_svc:
                    # La prestation a pu être citée à un tour précédent (« combien le
                    # balayage ? » → « je réserve ») : on la retrouve dans les derniers
                    # messages du client pour ne pas la redemander bêtement.
                    recent_user = " ".join(
                        m.get("content", "")
                        for m in state.message_history[-6:]
                        if m.get("role") == "user"
                    )
                    matched_svc = match_catalog_services(recent_user, request.catalog_services)
                if matched_svc:
                    state.set_slot("service", matched_svc, entity_type="SERVICE")

        # ── 4. Router vers l'agent (exécute l'action métier) ──
        state.phase = ConversationPhase.PROCESSING
        agent_result = await self._route_to_agent(state)
        state.agent_used = agent_result.get("agent", "fallback")
        state.action_result = agent_result.get("action_result")
        state.retrieved_documents = agent_result.get("documents", [])

        # ── Grounding RAG transverse ──
        # Seul l'agent FAQ interroge la base de connaissances. Or une question
        # informative est parfois mal classée (« vous avez un parking ? » → general,
        # « accessible en fauteuil ? » → planning) et court-circuite le RAG. Si aucun
        # document n'a été récupéré, que l'intention n'est pas purement sociale et
        # qu'aucune action n'a abouti, on cherche dans la base : les passages assez
        # pertinents (score ≥ seuil) sont injectés au générateur quel que soit l'agent
        # → Jenny se base sur sa connaissance même quand l'intention est mal classée.
        if (
            not state.retrieved_documents
            and self.retriever is not None
            and intent not in ("greeting", "closing", "escalation")
            and not (state.action_result or {}).get("success")
        ):
            try:
                _hits = await self.retriever.search(
                    request.message_text,
                    business_id=state.business_id,
                    top_k=3,
                    score_threshold=0.5,
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
            except Exception as _e:  # pragma: no cover - dépend de l'embedder/IO
                logger.warning("engine.rag_ground_failed", error=str(_e))

        # Suivi de confirmation : un RDV qui vient d'être réservé attend un « oui »
        # du client pour passer en confirmé ; une fois confirmé/annulé, on solde.
        _ar = state.action_result or {}
        if _ar.get("success") and _ar.get("appointment_id") and not _ar.get("operation"):
            state.awaiting_confirmation = True
        elif _ar.get("operation") in {"confirm", "cancel"}:
            state.awaiting_confirmation = False

        # Salon complet → on arme l'offre « liste d'attente » pour le tour suivant
        # (un « oui » inscrira le client). On garde la prestation/le jour en slots.
        if _ar.get("no_slots"):
            state.awaiting_waitlist = True
        # RDV pris pour un client sans nom → le prochain message sera son nom.
        if _ar.get("ask_name"):
            state.awaiting_name = True

        # ── Slot-filling prioritaire : une action attend une info manquante ──
        # (ex. RDV coiffeur sans la prestation/le jour/l'heure). Jenny la demande,
        # une à la fois, au lieu de deviner ou de répondre à côté.
        clarification_reason = ""
        if state.has_missing_required_slots():
            missing = state.get_missing_slots()
            state.clarification_instruction = _SLOT_ASK_FR.get(
                missing[0].name,
                "Demande poliment au client l'information manquante pour traiter sa demande.",
            )
            needs_clarification = True
            clarification_reason = "slot_filling"
            # On garde l'action en cours pour les prochains tours (continuité).
            state.pending_intent = intent
        elif intent == "appointment" and not (state.action_result or {}).get("success"):
            # RDV en cours : l'action propose des créneaux / signale un conflit /
            # attend l'heure → on GARDE la main jusqu'à la réservation effective,
            # et l'action a déjà la bonne consigne (pas de clarification générique).
            state.pending_intent = "appointment"
            needs_clarification = True
            clarification_reason = "booking_in_progress"
        else:
            # Action complète (ou pas d'action) → on libère le dialogue.
            state.pending_intent = None
            # ── Clarification générale (ambiguïté, vague, info clé manquante) ──
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

        # ── Lacune de connaissance : aucune réponse fiable disponible ? ──
        gap = is_knowledge_gap(
            intent=intent,
            documents=state.retrieved_documents,
            action_result=state.action_result,
        )
        # Le catalogue de prestations EST dans le prompt : une question de prix/devis
        # n'est donc PAS une lacune (Jenny doit citer le tarif, pas dire « je vérifie »).
        if gap and intent in ("pricing", "quote") and state.business_catalog:
            gap = False
        gap_question: str | None = None
        # On n'enregistre pas de lacune si on va déjà demander une clarification :
        # ce n'est pas « je ne sais pas », c'est « je n'ai pas compris ».
        if gap and not needs_clarification:
            state.knowledge_gap = True
            gap_question = clean_question(request.message_text)

        # Faits durables à mémoriser sur le client (persistés par la route).
        extracted_facts = extract_customer_facts(request.message_text)

        # ── 5. Générer la réponse via LLM (TOUJOURS) ──
        state.phase = ConversationPhase.RESPONDING
        response_text = await self._generate_response(state, on_token=on_token)

        # ── Affinage de la lacune après génération ──
        # Une réponse qui esquive (« je vérifie et je reviens ») trahit une
        # absence de réponse, même si un document proche avait un score correct.
        final_gap = refine_knowledge_gap(
            intent=intent,
            response_text=response_text,
            action_result=state.action_result,
            pre_gap=gap,
            needs_clarification=needs_clarification,
        )
        state.knowledge_gap = final_gap
        gap_question = clean_question(request.message_text) if final_gap else None

        # ── 6. Mettre à jour l'état ──
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
        """Détecte l'intention, en démasquant les demandes cachées par une politesse.

        Le modèle sur-classe en salutation dès qu'un message s'ouvre par une
        politesse ("Bonjour, je veux un devis" → greeting ~1.0, le devis est
        écrasé). On reclasse donc le message une fois la salutation retirée :
        si une vraie intention actionnable ressort franchement, c'est elle qui
        pilote le routage — la salutation reste juste un signal secondaire.
        """
        result = await self._classify_text(text)

        if result["intent"] in GREETING_INTENTS:
            remainder = self._strip_leading_greeting(text)
            if remainder:
                sub = await self._classify_text(remainder)
                if (
                    sub["intent"] not in GREETING_INTENTS
                    and sub["confidence"] >= GREETING_OVERRIDE_FLOOR
                ):
                    logger.info(
                        "engine.intent.greeting_unmasked",
                        masked_by=result["intent"],
                        real_intent=sub["intent"],
                        confidence=round(sub["confidence"], 3),
                    )
                    # On conserve la salutation comme intention secondaire.
                    sub["detected_intents"] = [
                        *sub["detected_intents"],
                        {"intent": result["intent"], "confidence": result["confidence"]},
                    ]
                    sub["is_multi_intent"] = True
                    sub["was_greeting"] = True
                    return sub

        return result

    async def _classify_text(self, text: str) -> dict:
        """Classifie un texte en intention (modèle ML si dispo, sinon règles).

        Le modèle ML prime quand il est confiant. En dessous du seuil
        `ML_CONFIDENCE_FLOOR`, on consulte les règles mots-clés : un match
        franc (ex. « devis », « rendez-vous ») est plus fiable qu'une
        prédiction ML floue, ce qui évite que du bruit ML (~0.2-0.4) écrase
        une intention évidente.
        """
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

        # Fallback : règles simples basées sur des mots-clés
        intent, confidence = self._rule_based_intent(text)
        return {
            "intent": intent,
            "confidence": confidence,
            "detected_intents": [{"intent": intent, "confidence": confidence}],
            "is_multi_intent": False,
            "needs_clarification": False,
        }

    def _strip_leading_greeting(self, text: str) -> str:
        """Retire une salutation en tête et renvoie le reste du message.

        "Bonjour, je veux un devis" → "je veux un devis".
        Renvoie "" si rien n'a été retiré, ou si le reste fait moins de deux
        mots : un fragment trop court ("Bonjour Jenny !" → "Jenny !") est une
        adresse polie, pas une demande, et ne doit pas déclencher de
        reclassement (sinon un prénom serait pris pour une intention).
        """
        remainder = _GREETING_PREFIX_RE.sub("", text, count=1).strip()
        if not remainder or remainder == text.strip():
            return ""
        if len(re.findall(r"\w+", remainder)) < 2:
            return ""
        return remainder

    def _rule_based_intent(self, text: str) -> tuple[str, float]:
        """Détection d'intention par règles (fallback)."""
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
        """Route vers l'agent approprié selon l'intention."""
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
        """Génère la réponse via le LLM (TOUJOURS prioritaire).

        Le LLM reçoit tout le contexte : intention, entités, résultat d'action,
        historique, documents RAG. C'est lui qui formule la réponse naturelle.
        Fallback sur templates uniquement si le LLM est indisponible.
        ``on_token`` diffuse la réponse au fil de l'eau si fourni.
        """
        if self.response_generator is not None:
            try:
                from jenny.engine.response_generator import ResponseGenerator

                if isinstance(self.response_generator, ResponseGenerator):
                    return await self.response_generator.generate(state, on_token=on_token)
            except (ImportError, Exception) as e:
                logger.warning("engine.generator.error", error=str(e))

        # Fallback UNIQUEMENT si pas de LLM
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
