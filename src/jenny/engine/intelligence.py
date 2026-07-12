"""Couche d'intelligence du moteur conversationnel.

Fonctions PURES (sans I/O ni accès base) qui décident, pour chaque message :

- **Langue** (`detect_language`) — pour répondre dans la langue du client.
- **Clarification** (`decide_clarification`) — Jenny pose une question de précision
  quand elle ne saisit pas bien le besoin (ambigu, vague, info clé manquante).
- **Lacune de connaissance** (`is_knowledge_gap`) — aucune réponse fiable dispo :
  on enregistre la question pour que le commerçant y réponde plus tard.
- **Faits client** (`extract_customer_facts`) — infos durables à mémoriser.

Conçues pour être appelées par ``ConversationEngine`` et testées isolément.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Langue
# ──────────────────────────────────────────────────────────────────────────────

# Codes ISO 639-1 → nom de langue (pour instruire le LLM clairement).
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
    """Détecte la langue d'un message (code ISO 639-1).

    Utilise ``langdetect`` (graine fixée pour des résultats déterministes). Les
    messages trop courts ou ambigus retombent sur ``default`` — sur 2-3 mots la
    détection n'est pas fiable et basculer de langue à tort serait pire.
    """
    cleaned = (text or "").strip()
    if len(cleaned) < 8 or len(re.findall(r"\w+", cleaned)) < 2:
        return default
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(cleaned)
        # langdetect renvoie parfois "zh-cn" : on garde la racine 2 lettres.
        code = code.split("-")[0].lower()
        return code if code in LANGUAGE_NAMES else default
    except Exception:  # pragma: no cover - dépend de l'entrée
        return default


def language_name(code: str | None) -> str:
    """Nom lisible d'une langue à partir de son code (fallback : français)."""
    return LANGUAGE_NAMES.get((code or "fr").lower(), "français")


# ──────────────────────────────────────────────────────────────────────────────
# Clarification
# ──────────────────────────────────────────────────────────────────────────────

# Intentions purement relationnelles : on ne demande jamais de précision.
_NO_CLARIFY_INTENTS = frozenset({"greeting", "small_talk", "closing", "escalation"})

# En dessous de cette confiance, une demande non triviale est jugée mal comprise.
CLARIFY_CONFIDENCE_FLOOR = 0.4

# Entité indispensable pour traiter certaines intentions actionnables.
# Si elle manque, Jenny la demande au lieu de deviner.
_REQUIRED_ENTITY: dict[str, tuple[str, str]] = {
    # intent: (clé d'entité attendue, formulation de ce qu'il faut demander)
    "order_status": ("order_number", "le numéro de commande"),
}


@dataclass
class ClarificationDecision:
    """Décision de clarification produite par la couche d'intelligence."""

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
    """Décide si Jenny doit demander une précision avant de répondre.

    Conservateur par construction : on ne clarifie que sur des signaux nets
    (ambiguïté multi-demande, demande très vague, ou info clé manquante) pour ne
    pas agacer le client avec des questions inutiles.
    """
    entities = entities or {}
    if intent in _NO_CLARIFY_INTENTS:
        return ClarificationDecision.none()

    # 1) Plusieurs demandes distinctes et actionnables dans le même message.
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

    # 2) Info clé manquante pour une intention actionnable.
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

    # 3) Demande très vague : message court + intention incertaine/générique.
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

# Intentions où le client attend une INFORMATION (pas une action pure).
KNOWLEDGE_SEEKING_INTENTS = frozenset(
    {"faq", "general", "pricing", "payment_question", "planning", "quote"}
)

# Score de pertinence RAG minimal pour considérer qu'on a une VRAIE réponse.
# ⚠️ Calibré sur l'échelle BLENDÉE du retriever (0.7·cosinus mpnet + 0.3·lexical,
# cf. rag/rerank.py) — recalibrer si le modèle d'embeddings ou le blend change,
# et RÉ-INDEXER la base (scripts/reindex_kb.py) à chaque changement de modèle.
# Mesuré les 2026-07-11/12 sur la KB de démo (paraphrase-multilingual-mpnet-base-v2,
# échelle BLENDÉE du retriever partagé — 0.7·cos + 0.3·lexical) :
# question DONT la réponse est en base → 0.39 à 0.67 ; hors-sujet franc
# (pneus, piano…) → ≤ 0.36 ; « même commerce mais service ABSENT » (extensions,
# épilation, permis moto…) → 0.32 à 0.52. Les bandes se CHEVAUCHENT : aucun
# scalaire ne sépare. On combine donc score ET couverture lexicale du SUJET :
#   < HARD_FLOOR                       → lacune (vraiment rien de pertinent) ;
#   [HARD_FLOOR, STRONG) & sujet ABSENT des docs → lacune (négatif « même métier
#       mais service absent » : « moto », « extensions »… absents des passages) ;
#   sinon (sujet présent OU score ≥ STRONG) → réponse présente.
# La couverture du sujet SAUVE les vraies questions dont le score frôle le
# plancher (« et vous faites les colorations ? » 0.39, doc « …colorations »
# présent) — c'était une source de fausses lacunes. Mieux vaut différer que
# mentir, mais pas au prix de faux « je vérifie » sur du contenu présent.
GAP_SCORE_HARD_FLOOR = 0.30
GAP_SCORE_STRONG = 0.60
# Rétrocompat (référencé par d'anciens tests / lectures) : borne basse de la bande.
GAP_SCORE_FLOOR = GAP_SCORE_HARD_FLOOR

# Mots non discriminants pour le veto de sujet : outils grammaticaux, verbes
# d'offre génériques, vocabulaire temporel (souvent absent du texte de la base
# alors que la réponse y est — « samedi matin » vs « 9h30-19h00 »), et POLITESSES
# (le message brut « super merci ! et vous faites les colorations ? » ne doit pas
# faire compter « super »/« merci » comme sujet distinctif absent des documents).
_SUBJECT_STOPWORDS = frozenset(
    {
        # Politesses / salutations / remerciements (jamais un « sujet »).
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
    """Vrai si un mot distinctif de la question est ABSENT des documents.

    Détecte le cas « même commerce mais service absent » : « posez-vous des
    extensions ? » matche sémantiquement un document « prestations : coupe,
    coloration… » (score moyen) alors que le SUJET demandé n'y figure pas.
    Comparaison par PRÉFIXE (4 lettres) : tolère pluriels, élisions et
    conjugaisons (« servez » ↔ « servons », « colorations » ↔ « coloration »).
    """
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
    """Vrai si une action a produit une donnée concrète (commande, créneau…)."""
    if not action_result:
        return False
    # On ignore les annotations internes (préfixées par « _ »).
    meaningful = {k: v for k, v in action_result.items() if not k.startswith("_")}
    if not meaningful:
        return False
    if meaningful.get("success") is True:
        return True
    # Présence d'une charge utile non vide (statut commande, créneaux, devis…).
    return any(bool(v) for k, v in meaningful.items() if k not in {"success", "error", "message"})


def is_knowledge_gap(
    *,
    intent: str,
    documents: list[dict] | None,
    action_result: dict | None,
    message: str = "",
) -> bool:
    """Détermine si Jenny n'a aucune réponse fiable à fournir.

    Vrai lorsque l'intention attend une information, qu'aucune action n'a produit
    de résultat concret, et que la base de connaissances ne renvoie rien de
    suffisamment pertinent : score sous le plancher, ou score moyen SANS que le
    sujet demandé apparaisse dans les documents (cf. ``_subject_uncovered``).
    """
    if intent not in KNOWLEDGE_SEEKING_INTENTS:
        return False
    if _action_has_concrete_result(action_result):
        return False
    docs = documents or []
    if not docs:
        return True
    top_score = max((d.get("score") or 0.0) for d in docs)
    # Rien de vraiment pertinent : lacune franche.
    if top_score < GAP_SCORE_HARD_FLOOR:
        return True
    # Score correct mais < STRONG : lacune UNIQUEMENT si le sujet demandé est
    # absent des passages (négatif « même métier, service absent »). Si le sujet
    # EST présent, la couverture lexicale prime même à score modeste → pas une
    # lacune (évite les faux « je vérifie » sur du contenu réellement en base).
    return top_score < GAP_SCORE_STRONG and _subject_uncovered(message, docs)


# Formules de « je n'ai pas la réponse, je vérifie » : le signal le plus fiable
# qu'une vraie réponse manquait, même quand un document proche a été retrouvé.
_DEFLECTION_RE = re.compile(
    r"je\s+v[ée]rifie|je\s+me\s+renseigne|je\s+reviens\s+vers\s+(?:vous|toi)|"
    r"v[ée]rifier\s+aupr[èe]s|mettre\s+en\s+relation|je\s+vous\s+recontacte|"
    r"transmets?\s+(?:votre|ta|la)\s+(?:demande|question)|on\s+revient\s+vers\s+(?:vous|toi)|"
    r"l['’]?[ée]quipe\s+(?:vous|te|pourra|reviendra|saura)|je\s+me\s+rapproche|"  # noqa: RUF001
    # Renvoyer vers l'équipe / son numéro est aussi une déflexion (= je n'ai pas l'info).
    r"contact\w*\s+(?:l['’]\s*|la\s+|notre\s+|directement\s+)*[ée]quipe|"  # noqa: RUF001
    r"(?:leur|son)\s+num[ée]ro|num[ée]ro\s+de\s+t[ée]l[ée]phone|"
    # « contactez-nous directement / venez en boutique pour ça » = même aveu.
    r"(?:nous|le)\s+contacter\s+directement|contacter\s+directement\s+(?:le|la|notre)|"
    r"recommande\s+de\s+(?:nous\s+)?contacter|venir\s+dans\s+notre\s+[ée]tablissement|"
    r"renseigner\s+aupr[èe]s",
    re.I,
)


def looks_like_deflection(text: str) -> bool:
    """Vrai si la réponse esquive (« je vérifie et je reviens vers vous »)."""
    return bool(_DEFLECTION_RE.search(text or ""))


def refine_knowledge_gap(
    *,
    intent: str,
    response_text: str,
    action_result: dict | None,
    pre_gap: bool,
    needs_clarification: bool,
) -> bool:
    """Décision FINALE de lacune, après génération de la réponse.

    Combine le signal de récupération (``pre_gap``) avec l'analyse de la réponse :
    si Jenny a esquivé (« je vérifie… »), c'est qu'elle n'avait pas l'info, même
    si un document proche avait un score correct. Corrige les faux négatifs où un
    document du même domaine masquait l'absence de réponse réelle.
    """
    deflected = looks_like_deflection(response_text)
    if _action_has_concrete_result(action_result):
        return False
    # Un prix concret a été donné (tarif depuis le catalogue) → question traitée,
    # même si la réponse propose aussi de « vérifier la disponibilité ».
    if intent in {"pricing", "quote"} and re.search(
        r"\d+\s*(?:€|euros?)", response_text or "", re.I
    ):
        return False
    # Une DÉFLEXION (« je vérifie et je reviens ») est par définition un aveu
    # d'absence de réponse : on la loggue comme lacune même si le modèle a signalé
    # une clarification (souvent une simple hésitation du classifieur d'intention)
    # ou si l'intention n'est pas « informative » — c'est le signal le plus fiable.
    if deflected:
        return True
    # Sinon : pas de lacune quand on demande une VRAIE clarification (« je n'ai pas
    # compris » ≠ « je ne sais pas ») ni pour les intentions non informatives.
    if needs_clarification or intent not in KNOWLEDGE_SEEKING_INTENTS:
        return False
    return bool(pre_gap)


def normalize_question(text: str, max_len: int = 200) -> str:
    """Empreinte normalisée d'une question (pour dédupliquer des variantes).

    Minuscule, sans accents ni ponctuation, espaces compactés. « Vous êtes
    ouverts le dimanche ? » et « ouvert dimanche » se rapprochent.
    """
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def clean_question(text: str, max_len: int = 280) -> str:
    """Nettoie une question pour l'afficher au propriétaire (trim + longueur)."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:max_len]


# ──────────────────────────────────────────────────────────────────────────────
# Faits client durables
# ──────────────────────────────────────────────────────────────────────────────

# Motifs à fort signal → fait durable + catégorie. Volontairement prudent :
# ces faits sont persistés, on évite donc le bruit.
_APOS = r"['’]"  # apostrophe droite ou typographique  # noqa: RUF001
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

# Conjonctions qui terminent un fait (évite de capturer deux idées en une).
_FACT_STOP_RE = re.compile(r"\s+(?:et|mais|car|donc|parce que|puis|ainsi que)\s+", re.I)

_MAX_FACTS_PER_MESSAGE = 3


def extract_customer_facts(text: str) -> list[dict[str, str]]:
    """Extrait des faits durables d'un message client (heuristique prudente).

    Renvoie une liste de ``{"fact": str, "kind": str}``. Vide si rien de net.
    """
    if not text:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern, kind in _FACT_PATTERNS:
        for m in pattern.finditer(text):
            snippet = re.sub(r"\s+", " ", m.group(0).strip()).rstrip(".")
            # Coupe à la première conjonction pour ne pas capturer deux idées.
            snippet = _FACT_STOP_RE.split(snippet, maxsplit=1)[0].strip()
            if len(snippet) < 4:
                continue
            key = normalize_question(snippet, max_len=120)
            if key in seen:
                continue
            seen.add(key)
            # Met une majuscule initiale, point final pour une phrase propre.
            fact = snippet[0].upper() + snippet[1:]
            if not fact.endswith((".", "!", "?")):
                fact += "."
            out.append({"fact": fact[:280], "kind": kind})
            if len(out) >= _MAX_FACTS_PER_MESSAGE:
                return out
    return out
