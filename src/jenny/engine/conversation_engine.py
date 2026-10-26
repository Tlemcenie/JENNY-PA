"""Moteur conversationnel principal de Jenny."""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jenny.agents.faq_agent import FAQ_MAX_DOCS, FAQ_MIN_SCORE, select_documents
from jenny.core.logging import get_logger
from jenny.engine.datetime_fr import (
    SOFT,
    VAGUE,
    fr_date_kind,
    parse_fr_date,
    parse_fr_duration,
    parse_fr_time,
    today_in,
)
from jenny.engine.intelligence import (
    clean_question,
    decide_clarification,
    detect_language,
    extract_customer_facts,
    is_knowledge_gap,
    refine_knowledge_gap,
)
from jenny.engine.state_manager import ConversationPhase, ConversationState, StateManager
from jenny.engine.thresholds import LATCH_MAX_TURNS, LOW_CONFIDENCE_FLOOR

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import date
    from uuid import UUID

    TokenCallback = Callable[[str], Awaitable[None]]

logger = get_logger(__name__)

# une inférence à la fois
_ML_LOCK = threading.Lock()


def _ml_call(fn: Callable[[str], object], text: str) -> object:
    """Inférence sous verrou."""
    with _ML_LOCK:
        return fn(text)


# seuil de confiance ML
ML_CONFIDENCE_FLOOR = 0.5

# réponse fixe au STOP
STOP_REPLY_TEXT = "C'est noté, vous ne recevrez plus nos offres. Je reste là pour vos rendez-vous."

# intentions de politesse
GREETING_INTENTS = frozenset({"greeting", "small_talk"})
# messages d'attente (« je regarde »)
_FILLER_INTENTS = frozenset({"greeting", "small_talk", "general"})

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

# avant « à demain » : début, ponctuation, merci
_BYE_LEAD = (
    # pas « jusqu'à demain »
    r"(?:^|[^\w\s'’]|\b(?:merci|ok|super|parfait|top|alors|et|bisous|bises|bcp|beaucoup|vous|"  # noqa: RUF001
    r"toi|encore|bon(?:ne)?\s+\w+))\s*"
)
_WD_FR = r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
_HOUR_FR = r"\d{1,2}\s*h(?:\s*\d{2})?"
# fin d'au revoir : merci, bisous
_BYE_TAIL = (
    rf"(?:alors|donc|matin|soir|midi|sans\s+faute|bisous|bises|bisou|{_HOUR_FR}|"
    r"(?:et\s+)?(?:encore\s+)?merci(?:\s+(?:encore|beaucoup|bcp|bien|infiniment|"
    r"[àa]\s+vous|pour\s+tout))?|j['’]ai\s+h[âa]te|[àa]\s+(?:vous|toi|tous)|"  # noqa: RUF001
    r"pour\s+(?:mon|ma|le|la|notre|votre)\s+(?:rdv|rendez[\s-]?vous|r[ée]servation)|"
    r"(?:et\s+)?bonne\s+(?:journ[ée]e|soir[ée]e|nuit|fin\s+de\s+journ[ée]e))"
)
# « merci, à jeudi 10h ! »
_FAREWELL_WHEN_RE = re.compile(
    rf"{_BYE_LEAD}[àa]\s+(?:demain|apr[èe]s[\s-]?demain|{_WD_FR}|"
    r"midi|tout\s+[àa]\s+l['’]heure)(?:\s+prochain)?(?:\s+en\s+(?:huit|quinze))?"  # noqa: RUF001
    rf"(?:[\s,]+(?:[àa]\s+)?(?:{_HOUR_FR}|midi))?"
    rf"(?:[^\w?]+{_BYE_TAIL})*[^\w?]*$",
    re.I,
)
# « bon week-end » : un souhait
_WISH_RE = re.compile(
    r"\bbon(?:ne)?\s+(?:week[\s-]?end|soir[ée]e|nuit|semaine|vacances|"
    r"apr[èe]s[\s-]?midi|aprem|fin\s+de\s+(?:journ[ée]e|semaine|soir[ée]e))\b"
    # « bon dimanche ! », pas « bon samedi 10h »
    rf"|\bbon(?:ne)?\s+(?:{_WD_FR})\b(?=\s*(?:$|[^\w\s?]|et\b|[àa]\s+(?:vous|toi|tous)\b))",
    re.I,
)
# « à ce soir », « à la prochaine »
_SEE_YOU_RE = re.compile(
    r"\b[àa]\s+(?:ce\s+(?:soir|midi|matin)|cet\s+apr[èe]s[\s-]?midi|cet\s+aprem|"
    r"tout\s+[àa]\s+l['’]heure|la\s+semaine\s+prochaine|la\s+prochaine|plus\s+tard|"  # noqa: RUF001
    r"tr[èe]s\s+vite|dans\s+(?:\d{1,2}|une?|deux|trois|quinze|huit)\s+(?:jours?|semaines?|mois))\b"
    # « à ce soir 18h »
    rf"(?:[\s,]+(?:[àa]\s+|vers\s+)?{_HOUR_FR})?",
    re.I,
)
# vrai signal de report
_RESCHED_CUE_RE = re.compile(
    r"\b(?:plut[ôo]t|finalement|en\s+fait|[àa]\s+la\s+place|au\s+lieu|pr[ée]f[èée]r\w*|mieux|"
    r"possible|dispo\w*|libre|de\s+la\s+place|arrang\w*|conv(?:ien|enir)\w*|"
    r"(?:[çc]a|cela)\s+(?:vous\s+|me\s+|m['’]\s?)?(?:va|irait|ira|marche|marcherait)|"  # noqa: RUF001
    r"(?:pouvez|pourriez|peux|pourrais|peut|pourrait)[\s-]+(?:vous\s+|on\s+)?"
    r"(?:me\s+|nous\s+|le\s+|la\s+|l['’]\s?)?(?:mettre|prendre|caser|passer|venir|avancer)|"  # noqa: RUF001
    r"autre\s+(?:jour|heure|cr[ée]neau|moment|date))\b",
    re.I,
)
# « et samedi ? »
_ALT_LEAD_RE = re.compile(r"^\s*(?:et|ou|sinon)\b", re.I)
# un 2e rdv, pas un report
_NEW_BOOKING_RE = re.compile(
    r"\b(?:un|une)\s+(?:autre|deuxi[èe]me|seconde?|nouveau|nouvel|nouvelle)\b"
    r"|\baussi\b|\b[ée]galement\b|\ben\s+plus\b",
    re.I,
)
# intentions d'au revoir
_BYE_INTENTS = frozenset({"closing", "greeting", "small_talk"})
# mots d'un créneau seul
_WHEN_TEXT = """
    a au aux le la les l du de d des en ce cet cette vers pile pour alors donc ben bon
    h heure heures er premier prochain prochaine suivant suivante matin soir midi minuit
    apres aprem demain aujourd hui plutot plus tot tard meme et demie demi quart moins
    huit quinze svp stp plait s il vous lundi mardi mercredi jeudi vendredi samedi dimanche
    janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre
"""
_WHEN_WORDS = frozenset(_WHEN_TEXT.split())

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

# vrai oui
_YES_RE = re.compile(
    r"^\s*(?:oui|ouais|ouaip|ouep|yes|yep|absolument|carr[ée]ment|volontiers|"
    r"tout\s+[àa]\s+fait|bien\s+s[ûu]r|exactement|[çc]a\s+me\s+va|je\s+valide|"
    r"ok\s+pour\s+moi|avec\s+plaisir|je\s+veux\s+bien)\b",
    re.I,
)
# accord léger, pas un oui
_ACK_RE = re.compile(
    r"^\s*(?:ok|okay|d['’]accord|dac|[çc]a\s+marche|parfait|super|top|nickel|"  # noqa: RUF001
    r"pourquoi\s+pas|go)\b",
    re.I,
)
# refus
_DECLINE_RE = re.compile(
    r"^\s*(?:non|nan|nope|pas\s+la\s+peine|pas\s+besoin|sans\s+fa[çc]on|"
    r"laisse[zr]?\s+tomber|tant\s+pis)\b|\bpas\s+int[ée]ress",
    re.I,
)


def is_confirmation(message: str) -> bool:
    """Vrai oui, pas une politesse."""
    m = message or ""
    return bool(_YES_RE.search(m)) and not _DECLINE_RE.search(m)


def accepts_offer(message: str) -> bool:
    """Accepte une proposition ?"""
    m = message or ""
    return bool(_YES_RE.search(m) or _ACK_RE.search(m)) and not _DECLINE_RE.search(m)


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
_NOT_NAME_TEXT = """
    moi lui elle nous vous eux toi ca cela ceci pour oui non ok okay oki ouais nan si yes no
    merci parfait super top genial nickel cool bien tres bon bonne daccord accord entendu note
    attends attendez attend patiente patientez seconde secondes instant minute minutes moment
    voila voici exact exactement absolument carrement volontiers surement bah euh hum hmm ah
    oh eh bof mdr lol ptdr haha quoi comment pourquoi quand combien qui je tu il on ils elles
    mon ma mes ton ta tes son sa ses notre votre leur et ou mais donc car puis alors aussi
    encore deja pas plus rien personne tout tous est suis sont etre ai as ont fait faire veux
    voudrais peux rdv rendez rendezvous reservation reserver annuler annule deplacer confirme
    confirmer coupe coiffure balayage couleur coloration brushing meches meche shampoing
    lissage permanente barbe soin soins frange demain aujourdhui matin soir midi apres aprem
    semaine weekend lundi mardi mercredi jeudi vendredi samedi dimanche janvier fevrier mars
    juin juillet aout septembre octobre novembre decembre salut bonjour bonsoir coucou
    hello hey svp stp plait desole desolee pardon vite urgent beaucoup infiniment plaisir
    avec un une les en au aux fin debut journee soiree nuit heure heures apresmidi plutot
    finalement possible dispo disponible libre place jenny gentil gentille sympa adorable
    degrade pointes carre chignon tresse tresses boucles racines keratine defrisage
    decoloration mise pli plis volume
"""
_NOT_NAME_WORDS = frozenset(_NOT_NAME_TEXT.split())
# de, la, van...
_NAME_PARTICLES = frozenset(
    {"de", "du", "des", "la", "le", "van", "von", "der", "den", "el", "al", "da", "di", "dos"}
)
# madame Dupont : titre pas compté
_CIVILITIES = frozenset({"madame", "monsieur", "mademoiselle", "mme", "mlle", "mr", "m"})
# « du volume », « le carré »
_ARTICLE_LEADS = frozenset({"de", "du", "des", "la", "le"})
# « merci Jenny » : pas son nom
_THANKS_RE = re.compile(r"\bmerci\b", re.I)
# « oui » devant le nom
_LEAD_FILLER_RE = re.compile(
    r"^\s*(?:(?:oui|ouais|ok|okay|d['’]accord|parfait|super|top|merci|alors|euh|bah|bon|"  # noqa: RUF001
    r"voil[àa]|tr[èe]s\s+bien|c['’]est\s+(?:bon|parfait|not[ée]))\b[\s,!.]*)+",  # noqa: RUF001
    re.I,
)
# découpe en morceaux
_NAME_SPLIT_RE = re.compile(r"[,;.!\n]+|\s+(?:et|mais)\s+", re.I)


def _word_key(word: str) -> str:
    return re.sub(r"['’\-]", "", _norm_txt(word))  # noqa: RUF001


def looks_like_name(text: str) -> bool:
    """Ressemble à un nom ?"""
    t = (text or "").strip()
    if not t or "?" in t or any(ch.isdigit() for ch in t):
        return False
    t = _NAME_INTRO_RE.sub("", t).strip(" .!,")  # retire le préfixe
    if not t:
        return False
    if _CLOSING_RE.search(t) or _GREETING_PREFIX_RE.match(t):
        return False
    words = t.split()
    # article + nom commun
    if _word_key(words[0]) in _ARTICLE_LEADS and len(words) > 1 and words[1][:1].islower():
        return False
    # particules et titres non comptés
    skip = _NAME_PARTICLES | _CIVILITIES
    core = [w for w in words if _word_key(w) not in skip]
    if not 1 <= len(core) <= 3 or len(words) > 5 or not _NAME_RE.match(t):
        return False
    # politesse, jour, prestation
    return not any(_word_key(w) in _NOT_NAME_WORDS for w in words)


def _split_lead(part: str) -> tuple[str, str]:
    """Sépare « oui, » du reste."""
    m = _LEAD_FILLER_RE.match(part)
    lead = m.group(0) if m else ""
    return lead, part[len(lead) :].strip()


def extract_customer_name(
    message: str, services: list[str] | None = None, business_name: str | None = None
) -> str | None:
    """Trouve le nom dans le message."""
    text = (message or "").strip()
    if not text or "?" in text:
        return None
    parts = [p.strip() for p in _NAME_SPLIT_RE.split(text) if p and p.strip()]
    # présentation explicite d'abord
    parts.sort(key=lambda p: 0 if _NAME_INTRO_RE.match(_split_lead(p)[1]) else 1)
    for part in parts:
        lead, cand = _split_lead(part)
        if not cand or (services and match_catalog_services(cand, services)):
            continue
        # « merci X » remercie X
        if _THANKS_RE.search(lead) and not _NAME_INTRO_RE.match(cand):
            continue
        if parse_fr_date(cand) or parse_fr_time(cand):
            continue
        if looks_like_name(cand):
            name = _NAME_INTRO_RE.sub("", cand).strip(" .!,")
            # le salon, pas le client
            if business_name and _norm_txt(name) == _norm_txt(business_name):
                continue
            return name
    return None


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
    # politesse ne confirme pas
    if awaiting_confirmation and is_confirmation(m):
        return "confirm"
    return None


def strip_farewell(message: str, *, keep_days: bool = False) -> str:
    """Retire « bon week-end », « à demain »."""
    m = _WISH_RE.sub(" ", message or "")
    # « décaler à jeudi » : on garde
    keep = (
        _MGMT_RESCHED_RE.search(m)
        or _MGMT_CANCEL_RE.search(m)
        or _RESCHED_CUE_RE.search(m)
        or re.search(r"\bavanc", m, re.I)
    )
    if not keep:
        m = _SEE_YOU_RE.sub(" ", m)
        # créneau proposé : « à jeudi 10h » = oui
        if not keep_days:
            m = _FAREWELL_WHEN_RE.sub(" ", m)
    return m


def is_farewell(message: str, *, today: date | None = None, keep_days: bool = False) -> bool:
    """Juste un au revoir ?"""
    rest = strip_farewell(message, keep_days=keep_days)
    if rest == (message or ""):
        return False
    return not (parse_fr_date(rest, today=today) or parse_fr_time(rest))


def _filled(state: ConversationState, name: str) -> str | None:
    """Valeur d'un slot rempli."""
    slot = state.slots.get(name)
    return slot.value if slot is not None and slot.filled else None


def _when_only(message: str) -> bool:
    """Juste un créneau ?"""
    return all(w in _WHEN_WORDS for w in re.findall(r"[a-z]+", _norm_txt(message)))


def is_implicit_reschedule(
    message: str,
    *,
    today: date,
    intent: str | None = None,
    services: list[str] | None = None,
    booked: tuple[str | None, str | None] = (None, None),
) -> bool:
    """Nouveau créneau = déplacer le rdv ?"""
    m = message or ""
    kind = fr_date_kind(m, today=today)
    hour = parse_fr_time(m)
    cue = bool(_RESCHED_CUE_RE.search(m))
    # jour flou ou bavardage
    if kind == VAGUE or (hour is None and (kind is None or (kind == SOFT and not cue))):
        return False
    if services and match_catalog_services(m, services):
        return False  # nouvelle prestation
    if _FAREWELL_WHEN_RE.search(m) or _NEW_BOOKING_RE.search(m) or looks_like_name(m):
        return False
    # même créneau qu'avant
    day = parse_fr_date(m, today=today)
    given = [
        (new, old)
        for new, old in zip(
            (day.isoformat() if day else None, hour.strftime("%H:%M") if hour else None),
            booked,
            strict=True,
        )
        if new
    ]
    if given and all(new == old for new, old in given):
        return False
    # au revoir : il faut un vrai signal
    if (
        _CLOSING_RE.search(m)
        or _WISH_RE.search(m)
        or _SEE_YOU_RE.search(m)
        or intent in _BYE_INTENTS
    ):
        return cue
    # « sinon jeudi ? », pas « et jeudi vous ouvrez ? »
    alt = _ALT_LEAD_RE.match(m)
    return cue or bool(alt and _when_only(m[alt.end() :])) or _when_only(m)


# clés NER gardées en slot
_ENTITY_SLOT_KEYS = frozenset(
    {
        "date",
        "time",
        "service",
        "duration",
        "phone",
        "email",
        "name",
        "order_number",
        "amount",
        "product",
        "location",
    }
)
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def coerce_entity(
    key: str, value: object, *, message: str = "", today: date | None = None
) -> str | None:
    """Valide une entité avant slot."""
    if key not in _ENTITY_SLOT_KEYS or value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if key == "date":
        d = parse_fr_date(v, today=today) or parse_fr_date(message, today=today)
        return d.isoformat() if d else None
    if key == "time":
        t = parse_fr_time(v) or parse_fr_time(message)
        return t.strftime("%H:%M") if t else None
    if key == "duration":
        n = parse_fr_duration(v)
        return str(n) if n else None
    if key == "phone":
        n_digits = len(re.sub(r"\D", "", v))
        return v if 8 <= n_digits <= 15 else None
    if key == "email":
        return v.lower() if _EMAIL_RE.match(v) else None
    if key == "amount":
        a = v.replace("€", "").replace(" ", "").replace(",", ".")
        try:
            x = float(a)
        except ValueError:
            return None
        return f"{x:.2f}" if 0 <= x < 1_000_000 else None
    # texte libre borné
    return v[:120]


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
    # fuseau du salon
    timezone: str | None = None


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
        state = await self.state_manager.aget_or_create(
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
        if request.timezone:
            state.business_timezone = request.timezone

        # STOP : désinscription, sans LLM
        stopped = await self._handle_stop(request, state)
        if stopped is not None:
            return stopped

        # consignes du tour d'avant
        state.clarification_instruction = None
        state.knowledge_gap = False
        # verrous trop vieux
        state.expire_latches(LATCH_MAX_TURNS)
        today = today_in(state.business_timezone)
        prev_pending = state.pending_intent
        # créneaux proposés au tour d'avant
        _prev_ar = state.action_result or {}
        _offered = prev_pending in ("appointment", "manage_appointment") and bool(
            _prev_ar.get("propose_slots") or _prev_ar.get("alternatives_text")
        )

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
        # « bon week-end » : pas un jour
        _when_txt = strip_farewell(_msg_txt, keep_days=_offered)
        _farewell = is_farewell(_msg_txt, today=today, keep_days=_offered)
        # jour ou heure dans le message
        _slot_in_msg = bool(parse_fr_date(_when_txt, today=today) or parse_fr_time(_when_txt))
        # rdv sans mot-clé
        _has_when = False
        if not _blocks_appt_override:
            _has_when = bool(parse_fr_date(_when_txt, today=today) or parse_fr_time(_when_txt))
        _has_service = bool(
            request.catalog_services and match_catalog_services(_msg_txt, request.catalog_services)
        )
        _strong_appt = bool(_STRONG_APPOINTMENT_RE.search(_msg_txt))
        _wants_appt = _strong_appt or (_has_when and _has_service)
        if _wants_appt and not _blocks_appt_override and not _farewell:
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

        # « à demain pour mon rdv » : un au revoir
        _bye_only = (
            _farewell
            and "?" not in _msg_txt
            and not _STRONG_APPOINTMENT_RE.search(_when_txt)
            and len(re.findall(r"\w+", _when_txt)) <= 4
        )
        if _bye_only and intent_result["intent"] in (
            "appointment",
            "manage_appointment",
            "planning",
        ):
            logger.info("engine.intent.farewell_to_closing", was=intent_result["intent"])
            intent_result = {
                **intent_result,
                "intent": "closing",
                "confidence": max(intent_result.get("confidence", 0.0), 0.8),
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
            msg_l = request.message_text or ""
            real_closing = (intent == "closing" and bool(_CLOSING_RE.search(msg_l))) or _farewell
            # « merci, à jeudi 10h » choisit le créneau
            if _offered and _slot_in_msg:
                real_closing = False
            hard_interrupt = intent in _INTERRUPTING_INTENTS or real_closing
            # complète une prise de rdv ?
            provides_appt_info = state.pending_intent == "appointment" and _slot_in_msg
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

        msg_text = request.message_text or ""
        # vrai changement de sujet ?
        new_topic = len(re.findall(r"\w+", msg_text)) > 3 and intent not in _FILLER_INTENTS

        # liste d'attente
        joining_waitlist = state.awaiting_waitlist and accepts_offer(msg_text)
        if joining_waitlist:
            state.disarm_latch("awaiting_waitlist")
            intent = "join_waitlist"
            intent_confidence = 0.95
            state.pending_intent = None
        elif state.awaiting_waitlist and (_DECLINE_RE.search(msg_text) or new_topic):
            # refus ou autre sujet
            state.disarm_latch("awaiting_waitlist")

        # nom attendu ?
        name_value = (
            extract_customer_name(msg_text, request.catalog_services, state.business_name)
            if state.awaiting_name and not joining_waitlist
            else None
        )

        # gestion du rdv, le nom prime
        mgmt_op = (
            None
            if joining_waitlist
            else detect_appointment_mgmt(msg_text, state.awaiting_confirmation and not name_value)
        )

        # report implicite sans mot-clé
        if mgmt_op is None and not joining_waitlist and not name_value:
            _appt_slot = state.slots.get("appointment_id")
            if (
                _appt_slot is not None
                and _appt_slot.filled
                and is_implicit_reschedule(
                    msg_text,
                    today=today,
                    intent=intent,
                    services=request.catalog_services,
                    booked=(state.booked_date, state.booked_time),
                )
            ):
                logger.info("engine.reschedule.implicit", appt="known")
                mgmt_op = "reschedule"

        # oui attendu, autre sujet
        if state.awaiting_confirmation and not mgmt_op and new_topic:
            state.disarm_latch("awaiting_confirmation")

        # capture du nom
        naming = name_value is not None and not mgmt_op
        if naming:
            state.disarm_latch("awaiting_name")

        # capture du téléphone
        from jenny.actions.handlers.set_customer_phone import extract_phone

        _phone_in_msg = extract_phone(msg_text)
        phoning = (
            state.awaiting_phone
            and not joining_waitlist
            and not mgmt_op
            and not naming
            and _phone_in_msg is not None
        )
        if phoning:
            state.disarm_latch("awaiting_phone")
        if naming:
            intent = "set_customer_name"
            intent_confidence = 0.95
            state.pending_intent = None
            state.set_slot("name", name_value)
        elif phoning:
            intent = "set_customer_phone"
            intent_confidence = 0.95
            state.pending_intent = None
            state.set_slot("phone", _phone_in_msg)
        elif mgmt_op:
            intent = "manage_appointment"
            intent_confidence = 0.9

        # flux quitté : slots vides oubliés
        if prev_pending and intent != prev_pending and not _resume_appointment_after_info:
            state.drop_missing_placeholders()

        state.set_intent(intent, intent_confidence)

        if mgmt_op:
            state.set_slot("operation", mgmt_op)
            state.pending_intent = None

        # 3. entités, liste blanche
        entities = await self._extract_entities(msg_text, state)
        for entity_name, entity_value in entities.items():
            # déjà capté par le verrou
            if (naming and entity_name == "name") or (phoning and entity_name == "phone"):
                continue
            # « à ce soir » : pas un créneau
            if _when_txt != _msg_txt and entity_name in ("date", "time"):
                continue
            clean = coerce_entity(entity_name, entity_value, message=msg_text, today=today)
            if clean is not None:
                state.set_slot(entity_name, clean, entity_type=entity_name.upper())

        # dates/heures en absolu
        if intent in ("appointment", "manage_appointment"):
            msg = msg_text.strip()
            # sans la formule d'au revoir
            _day = parse_fr_date(_when_txt, today=today)
            if _day:
                state.set_slot("date", _day.isoformat(), entity_type="DATE")
            _hour = parse_fr_time(_when_txt)
            if _hour:
                state.set_slot("time", _hour.strftime("%H:%M"), entity_type="TIME")
            # fallback prestation via catalogue
            svc_slot = state.slots.get("service")
            if not (svc_slot and svc_slot.filled) and request.catalog_services:
                matched_svc = match_catalog_services(msg, request.catalog_services)
                if not matched_svc:
                    # citée depuis la purge
                    recent_user = " ".join(state.user_messages_since_reset(6))
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
                # même seuil que la FAQ
                _hits = await self.retriever.search(
                    request.message_text,
                    business_id=state.business_id,
                    top_k=FAQ_MAX_DOCS,
                    score_threshold=FAQ_MIN_SCORE,
                )
                _docs = select_documents(
                    [
                        {"content": h.content, "score": h.score, "metadata": h.metadata}
                        for h in _hits or []
                    ]
                )
                if _docs:
                    state.retrieved_documents = _docs
                    logger.info(
                        "engine.rag_grounded",
                        results=len(_docs),
                        top_score=round(_docs[0]["score"], 3),
                    )
            except Exception as _e:  # pragma: no cover
                logger.warning("engine.rag_ground_failed", error=str(_e))

        # suivi de confirmation
        _ar = state.action_result or {}
        _ok = bool(_ar.get("success"))
        _booked = _ok and intent == "appointment" and not _ar.get("operation")
        if _ok and _ar.get("appointment_id") and not _ar.get("operation"):
            state.arm_latch("awaiting_confirmation")
        elif _ar.get("operation") in {"confirm", "cancel"}:
            state.disarm_latch("awaiting_confirmation")

        # salon complet: liste d'attente
        if _ar.get("no_slots"):
            state.arm_latch("awaiting_waitlist")
        elif _booked:
            state.disarm_latch("awaiting_waitlist")
        # client sans nom
        if _ar.get("ask_name"):
            state.arm_latch("awaiting_name")
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
            state.arm_latch("awaiting_phone")
        # créneau du rdv actuel
        _op = _ar.get("operation")
        if _booked or (_ok and _op == "reschedule"):
            _keep = _op == "reschedule"
            state.booked_date = _filled(state, "date") or (state.booked_date if _keep else None)
            state.booked_time = _filled(state, "time") or (state.booked_time if _keep else None)
        elif _ok and _op == "cancel":
            state.booked_date = state.booked_time = None
        # rdv fait, on purge
        if _booked or (_ok and (_ar.get("operation") or _ar.get("waitlisted"))):
            state.reset_booking_slots()

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
            state.pending_intent = "appointment" if _resume_appointment_after_info else intent
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
        await self.state_manager.asave(state)

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
            requires_human=intent == "escalation" or intent_confidence < LOW_CONFIDENCE_FLOOR,
            detected_language=state.detected_language,
            knowledge_gap=state.knowledge_gap,
            gap_question=gap_question,
            extracted_facts=extracted_facts or None,
        )

    async def _handle_stop(
        self, request: EngineRequest, state: ConversationState
    ) -> EngineResponse | None:
        """STOP : plus d'offres, réponse fixe."""
        from jenny.services.offer_cap import apply_stop_reply, is_stop_reply

        customer_id = request.customer_id or state.customer_id
        if customer_id is None or not is_stop_reply(request.message_text):
            return None
        try:
            from jenny.db.session import async_session_factory

            async with async_session_factory() as db:
                done = await apply_stop_reply(
                    db,
                    business_id=request.business_id,
                    customer_id=customer_id,
                    text=request.message_text,
                )
                if done:
                    await db.commit()
        except Exception as e:
            logger.error("engine.stop_reply_error", error=str(e))
            return None
        if not done:
            return None

        logger.info("engine.stop_reply", customer_id=str(customer_id))
        state.set_intent("opt_out", 1.0)
        state.pending_intent = None
        state.agent_used = "opt_out"
        state.action_result = {"success": True, "opted_out": True}
        state.retrieved_documents = []
        state.phase = ConversationPhase.CLOSING
        state.suggested_response = STOP_REPLY_TEXT
        state.add_assistant_message(STOP_REPLY_TEXT)
        await self.state_manager.asave(state)
        return EngineResponse(
            response_text=STOP_REPLY_TEXT,
            intent="opt_out",
            intent_confidence=1.0,
            detected_intents=[{"intent": "opt_out", "confidence": 1.0}],
            agent_used="opt_out",
            action_result=dict(state.action_result),
            conversation_phase=state.phase.value,
            detected_language=state.detected_language,
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
        # lstm ou tête mpnet : même api
        predict_multi = getattr(self.intent_predictor, "predict_multi", None)
        if callable(predict_multi):
            try:
                # hors boucle d'événements
                result = await asyncio.to_thread(_ml_call, predict_multi, text)
                ml_intent = result["primary_intent"]
                ml_conf = float(result["primary_confidence"])

                if ml_conf < ML_CONFIDENCE_FLOOR:
                    rule_intent, rule_conf = self._rule_based_intent(text)
                    if rule_intent != "general" and rule_conf > ml_conf:
                        return {
                            "intent": rule_intent,
                            "confidence": rule_conf,
                            "detected_intents": [{"intent": rule_intent, "confidence": rule_conf}],
                            "is_multi_intent": False,
                            "needs_clarification": False,
                        }

                return {
                    "intent": ml_intent,
                    "confidence": ml_conf,
                    "detected_intents": result.get("intents")
                    or [{"intent": ml_intent, "confidence": ml_conf}],
                    "is_multi_intent": bool(result.get("is_multi_intent", False)),
                    "needs_clarification": bool(result.get("needs_clarification", False)),
                }
            except Exception as e:
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
        regex_entities = self._regex_entity_extraction(text)
        predict = getattr(self.ner_predictor, "predict", None)
        if callable(predict):
            try:
                # hors boucle d'événements
                found = await asyncio.to_thread(_ml_call, predict, text)
                entities = dict(found or {})
                # regex en complément
                for key, value in regex_entities.items():
                    entities.setdefault(key, value)
                return entities
            except Exception as e:
                logger.warning("engine.ner.model_error", error=str(e))

        return regex_entities

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
