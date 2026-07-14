"""Intelligence pure du moteur."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Langue
# ──────────────────────────────────────────────────────────────────────────────

# code ISO → nom
LANGUAGE_NAMES: dict[str, str] = {
    "fr": "français",
    "en": "anglais",
    "es": "espagnol",
    "de": "allemand",
    "it": "italien",
    "pt": "portugais",
    "nl": "néerlandais",
    "ar": "arabe",
    "ca": "catalan",
}


def detect_language(text: str, default: str = "fr") -> str:
    """Détecte la langue."""
    cleaned = (text or "").strip()
    if len(cleaned) < 8 or len(re.findall(r"\w+", cleaned)) < 2:
        return default
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(cleaned)
        # garde les 2 lettres
        code = code.split("-")[0].lower()
        return code if code in LANGUAGE_NAMES else default
    except Exception:  # pragma: no cover
        return default


def language_name(code: str | None) -> str:
    """Nom lisible d'une langue."""
    return LANGUAGE_NAMES.get((code or "fr").lower(), "français")


# ──────────────────────────────────────────────────────────────────────────────
# Clarification
# ──────────────────────────────────────────────────────────────────────────────

# intentions relationnelles
_NO_CLARIFY_INTENTS = frozenset({"greeting", "small_talk", "closing", "escalation"})

# seuil de confiance
CLARIFY_CONFIDENCE_FLOOR = 0.4

# entité obligatoire
# sinon on la demande
_REQUIRED_ENTITY: dict[str, tuple[str, str]] = {
    # intent: (clé, libellé)
    "order_status": ("order_number", "le numéro de commande"),
}


@dataclass
class ClarificationDecision:
    """Décision de clarification."""

    needs_clarification: bool
    reason: str = ""
    instruction: str = ""
    ask_about: str = ""

    @classmethod
    def none(cls) -> ClarificationDecision:
        return cls(needs_clarification=False)


def _meaningful_words(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 1]


def decide_clarification(
    *,
    message_text: str,
    intent: str,
    confidence: float,
    entities: dict[str, str] | None = None,
    detected_intents: list | None = None,
    is_multi_intent: bool = False,
) -> ClarificationDecision:
    """Faut-il demander une précision ?"""
    entities = entities or {}
    if intent in _NO_CLARIFY_INTENTS:
        return ClarificationDecision.none()

    # 1) plusieurs demandes
    if is_multi_intent and detected_intents:
        distinct = {
            d.get("intent")
            for d in detected_intents
            if isinstance(d, dict)
            and d.get("intent") not in _NO_CLARIFY_INTENTS
            and (d.get("confidence") or 0) >= 0.35
        }
        if len(distinct) >= 2:
            labels = ", ".join(sorted(distinct))
            return ClarificationDecision(
                True,
                reason="multi_intent",
                ask_about=labels,
                instruction=(
                    "Le client semble formuler plusieurs demandes à la fois "
                    f"({labels}). Avant de répondre, demande-lui gentiment de "
                    "préciser par laquelle commencer, en une phrase."
                ),
            )

    # 2) info clé manquante
    if intent in _REQUIRED_ENTITY:
        key, human = _REQUIRED_ENTITY[intent]
        if not entities.get(key):
            return ClarificationDecision(
                True,
                reason="missing_entity",
                ask_about=human,
                instruction=(
                    f"Pour aider le client, il te faut {human}, qui n'a pas été "
                    "fourni. Demande-le-lui simplement et chaleureusement."
                ),
            )

    # 3) demande trop vague
    words = _meaningful_words(message_text)
    is_vague_generic = intent in {"general", "faq"} and confidence < CLARIFY_CONFIDENCE_FLOOR
    if (len(words) <= 3 and is_vague_generic) or (len(words) <= 2 and intent == "general"):
        return ClarificationDecision(
            True,
            reason="too_vague",
            instruction=(
                "Le message du client est court et son besoin n'est pas clair. "
                "Pose-lui une question ouverte et chaleureuse pour comprendre "
                "précisément ce qu'il souhaite, sans deviner."
            ),
        )

    return ClarificationDecision.none()


# ──────────────────────────────────────────────────────────────────────────────
# Lacune de connaissance
# ──────────────────────────────────────────────────────────────────────────────

# intentions qui attendent une info
KNOWLEDGE_SEEKING_INTENTS = frozenset(
    {"faq", "general", "pricing", "payment_question", "planning", "quote"}
)

# seuil RAG de vraie réponse
GAP_SCORE_HARD_FLOOR = 0.30
GAP_SCORE_STRONG = 0.60
# rétrocompat, ancienne borne
GAP_SCORE_FLOOR = GAP_SCORE_HARD_FLOOR

# mots non discriminants (veto sujet)
_SUBJECT_STOPWORDS = frozenset(
    {
        # politesses
        "bonjour",
        "bonsoir",
        "salut",
        "coucou",
        "hello",
        "merci",
        "super",
        "genial",
        "génial",
        "parfait",
        "nickel",
        "cool",
        "svp",
        "stp",
        "plait",
        "plaît",
        "hey",
        "voila",
        "voilà",
        "alors",
        "donc",
        "juste",
        "aussi",
        "vraiment",
        "peut-etre",
        "peutetre",
        "vous",
        "nous",
        "votre",
        "notre",
        "vos",
        "leurs",
        "elle",
        "elles",
        "avec",
        "pour",
        "dans",
        "chez",
        "cette",
        "cela",
        "quoi",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "comment",
        "combien",
        "quand",
        "est",
        "sont",
        "etes",
        "êtes",
        "avez",
        "bien",
        "tout",
        "toute",
        "faites",
        "faire",
        "posez",
        "poser",
        "proposez",
        "proposer",
        "vendez",
        "vendre",
        "utilisez",
        "utiliser",
        "prenez",
        "prendre",
        "peut",
        "peux",
        "pouvez",
        "possible",
        "besoin",
        "savoir",
        "voudrais",
        # fillers de suivi
        "fais",
        "fait",
        "faut",
        "coup",
        "veux",
        "veut",
        "dois",
        "doit",
        "sais",
        "sait",
        "vais",
        "dire",
        "dis",
        "chose",
        "truc",
        "fois",
        "quelque",
        "quelqu",
        "plutot",
        "plutôt",
        "genre",
        "sinon",
        "enfin",
        "matin",
        "soir",
        "midi",
        "apres",
        "après",
        "week",
        "weekend",
        "aujourd",
        "demain",
        "semaine",
        "heure",
        "heures",
        "jour",
        "jours",
        "prix",
        "tarif",
        "tarifs",
        "coute",
        "coûte",
        "jusqu",
        "jusque",
        "depuis",
        "entre",
        "pendant",
        "chaque",
        "encore",
        "servez",
        "servons",
        "ouvrez",
        "fermez",
        "restez",
        "ouvert",
        "ouverts",
        "ouverte",
        "ouvertes",
    }
)


def _subject_uncovered(message: str, docs: list[dict]) -> bool:
    """Sujet absent des documents ?"""
    tokens = {
        t
        for t in re.findall(r"[a-zà-ÿ0-9]+", (message or "").lower())
        if len(t) >= 4 and t not in _SUBJECT_STOPWORDS
    }
    if not tokens:
        return False
    blob = " ".join((d.get("content") or "").lower() for d in docs[:3])
    return any(t[:4] not in blob for t in tokens)


def _action_has_concrete_result(action_result: dict | None) -> bool:
    """Action avec résultat concret ?"""
    if not action_result:
        return False
    # ignore les clés internes
    meaningful = {k: v for k, v in action_result.items() if not k.startswith("_")}
    if not meaningful:
        return False
    if meaningful.get("success") is True:
        return True
    # une charge utile non vide
    return any(bool(v) for k, v in meaningful.items() if k not in {"success", "error", "message"})


def _retrieval_has_answer(documents: list[dict] | None, message: str) -> bool:
    """La récupération fonde-t-elle une réponse ?"""
    docs = documents or []
    if not docs:
        return False
    top_score = max((d.get("score") or 0.0) for d in docs)
    if top_score < GAP_SCORE_HARD_FLOOR:
        return False
    return top_score >= GAP_SCORE_STRONG or not _subject_uncovered(message, docs)


def is_knowledge_gap(
    *,
    intent: str,
    documents: list[dict] | None,
    action_result: dict | None,
    message: str = "",
) -> bool:
    """Jenny n'a aucune réponse fiable ?"""
    if intent not in KNOWLEDGE_SEEKING_INTENTS:
        return False
    if _action_has_concrete_result(action_result):
        return False
    return not _retrieval_has_answer(documents, message)


# formules « je vérifie »
_DEFLECTION_RE = re.compile(
    r"je\s+v[ée]rifie|je\s+me\s+renseigne|je\s+reviens\s+vers\s+(?:vous|toi)|"
    r"v[ée]rifier\s+aupr[èe]s|mettre\s+en\s+relation|je\s+vous\s+recontacte|"
    r"transmets?\s+(?:votre|ta|la)\s+(?:demande|question)|on\s+revient\s+vers\s+(?:vous|toi)|"
    r"l['’]?[ée]quipe\s+(?:vous|te|pourra|reviendra|saura)|je\s+me\s+rapproche|"  # noqa: RUF001
    # renvoi équipe = déflexion
    r"contact\w*\s+(?:l['’]\s*|la\s+|notre\s+|directement\s+)*[ée]quipe|"  # noqa: RUF001
    r"(?:leur|son)\s+num[ée]ro|num[ée]ro\s+de\s+t[ée]l[ée]phone|"
    # « contactez-nous » = aveu
    r"(?:nous|le)\s+contacter\s+directement|contacter\s+directement\s+(?:le|la|notre)|"
    r"recommande\s+de\s+(?:nous\s+)?contacter|venir\s+dans\s+notre\s+[ée]tablissement|"
    r"renseigner\s+aupr[èe]s",
    re.I,
)


def looks_like_deflection(text: str) -> bool:
    """La réponse esquive ?"""
    return bool(_DEFLECTION_RE.search(text or ""))


def refine_knowledge_gap(
    *,
    intent: str,
    response_text: str,
    action_result: dict | None,
    pre_gap: bool,
    needs_clarification: bool,
    retrieval_grounded: bool = False,
) -> bool:
    """Décision finale de lacune."""
    if _action_has_concrete_result(action_result):
        return False
    # prix concret donné
    # = question traitée
    if intent in {"pricing", "quote"} and re.search(
        r"\d+\s*(?:€|euros?)", response_text or "", re.I
    ):
        return False
    deflected = looks_like_deflection(response_text)
    # vraie clarification
    # pas une lacune
    if needs_clarification and not deflected:
        return False
    if pre_gap:
        return True
    # récup fondée → jamais lacune
    if retrieval_grounded:
        return False
    # non fondé + déflexion → lacune
    # rattrape les mal classées
    return deflected


def normalize_question(text: str, max_len: int = 200) -> str:
    """Empreinte normalisée d'une question."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def clean_question(text: str, max_len: int = 280) -> str:
    """Nettoie une question pour l'affichage."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:max_len]


# ──────────────────────────────────────────────────────────────────────────────
# Faits client durables
# ──────────────────────────────────────────────────────────────────────────────

# motifs à fort signal
# prudent, on évite le bruit
_APOS = r"['’]"  # apostrophe  # noqa: RUF001
_FACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bje\s+suis\s+allergique\s+(?:[àa]|au|aux)\s+([^.,;!?\n]{2,60})", re.I),
        "constraint",
    ),
    (re.compile(r"\bje\s+pr[ée]f[èe]re\s+([^.,;!?\n]{2,70})", re.I), "preference"),
    (re.compile(rf"\bj{_APOS}?\s*aime\s+(?:bien\s+)?([^.,;!?\n]{{2,70}})", re.I), "preference"),
    (re.compile(rf"\bje\s+n{_APOS}?\s*aime\s+pas\s+([^.,;!?\n]{{2,70}})", re.I), "preference"),
    (re.compile(rf"\bj{_APOS}?\s*[ée]vite\s+([^.,;!?\n]{{2,60}})", re.I), "constraint"),
    (re.compile(rf"\bje\s+m{_APOS}?\s*appelle\s+([A-Za-zÀ-ž][\w'-]{{1,40}})", re.I), "contact"),
    (
        re.compile(r"\bje\s+suis\s+(?:cliente?|client)\s+(depuis\s+[^.,;!?\n]{2,40})", re.I),
        "context",
    ),
]

# conjonctions qui coupent un fait
_FACT_STOP_RE = re.compile(r"\s+(?:et|mais|car|donc|parce que|puis|ainsi que)\s+", re.I)

_MAX_FACTS_PER_MESSAGE = 3


def extract_customer_facts(text: str) -> list[dict[str, str]]:
    """Extrait les faits durables."""
    if not text:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern, kind in _FACT_PATTERNS:
        for m in pattern.finditer(text):
            snippet = re.sub(r"\s+", " ", m.group(0).strip()).rstrip(".")
            # coupe à la 1re conjonction
            snippet = _FACT_STOP_RE.split(snippet, maxsplit=1)[0].strip()
            if len(snippet) < 4:
                continue
            key = normalize_question(snippet, max_len=120)
            if key in seen:
                continue
            seen.add(key)
            # majuscule + point final
            fact = snippet[0].upper() + snippet[1:]
            if not fact.endswith((".", "!", "?")):
                fact += "."
            out.append({"fact": fact[:280], "kind": kind})
            if len(out) >= _MAX_FACTS_PER_MESSAGE:
                return out
    return out
