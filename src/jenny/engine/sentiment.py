"""Analyse de sentiment légère (lexique FR), sans appel LLM.

But : repérer rapidement un client mécontent pour le signaler (flag + tag) et,
le cas échéant, déclencher une escalade. Volontairement simple et déterministe
(pas de coût LLM, exécutable de façon synchrone à l'ingestion).
"""

from __future__ import annotations

import re

# Mots/expressions à forte charge négative (mécontentement, colère, litige).
_NEGATIVE = {
    "nul",
    "nulle",
    "horrible",
    "honteux",
    "honteuse",
    "scandale",
    "scandaleux",
    "inadmissible",
    "inacceptable",
    "déçu",
    "decu",
    "déçue",
    "decue",
    "déception",
    "deception",
    "arnaque",
    "arnaquer",
    "voleur",
    "vol",
    "remboursement",
    "rembourser",
    "remboursez",
    "plainte",
    "porter plainte",
    "avocat",
    "litige",
    "colère",
    "colere",
    "furieux",
    "furieuse",
    "énervé",
    "enerve",
    "énervée",
    "marre",
    "ras-le-bol",
    "jamais",
    "pire",
    "catastrophe",
    "catastrophique",
    "lamentable",
    "incompétent",
    "incompetent",
    "incompétence",
    "honte",
    "abusé",
    "abuse",
    "mécontent",
    "mecontent",
    "mécontente",
    "insatisfait",
    "insatisfaite",
    "problème",
    "probleme",
    "réclamation",
    "reclamation",
    "annuler",
    "annulation",
    "résilier",
    "resilier",
}

# Mots à charge positive (satisfaction, remerciement).
_POSITIVE = {
    "merci",
    "génial",
    "genial",
    "super",
    "parfait",
    "excellent",
    "excellente",
    "top",
    "ravi",
    "ravie",
    "content",
    "contente",
    "satisfait",
    "satisfaite",
    "bravo",
    "formidable",
    "magnifique",
    "adore",
    "adorable",
    "impeccable",
    "nickel",
    "rapide",
    "efficace",
    "recommande",
}

_WORD_RE = re.compile(r"[a-zàâäéèêëîïôöùûüç'-]+", re.IGNORECASE)


def analyze_sentiment(text: str | None) -> str:
    """Renvoie ``positive``, ``negative`` ou ``neutral`` pour un texte donné."""
    if not text:
        return "neutral"
    words = {w.lower() for w in _WORD_RE.findall(text)}
    neg = len(words & _NEGATIVE)
    pos = len(words & _POSITIVE)
    # La négativité prime (un client mécontent ne doit pas passer inaperçu).
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def is_negative(text: str | None) -> bool:
    return analyze_sentiment(text) == "negative"
