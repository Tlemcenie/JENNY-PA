"""ner filtré pour les slots."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from ml.models.ner.predict import NERPredictor

# racines de prestations salon
SERVICE_STEMS = (
    "coupe",
    "colo",
    "couleur",
    "decolor",
    "balayage",
    "meche",
    "brushing",
    "lissage",
    "keratine",
    "defrisage",
    "permanente",
    "boucl",
    "soin",
    "masque",
    "shampo",
    "barbe",
    "rasage",
    "rase",
    "degrade",
    "carre",
    "frange",
    "chignon",
    "tresse",
    "natte",
    "coiff",
    "plis",
    "extension",
    "ombre",
    "babylight",
    "patine",
    "gloss",
    "henne",
    "cils",
    "sourcil",
    "epilation",
    "manucure",
    "pedicure",
    "ongle",
    "maquillage",
    "massage",
    "consultation",
    "diagnostic",
    "traitement",
    "capillaire",
    "cheveu",
    "chevelu",
    "scalp",
    "hair",
    "tie and dye",
)
# fautes légères
FUZZY_MIN = 0.8
# jours, heures : hors prestation
_WHEN_WORDS = {
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
    "demain",
    "apres-demain",
    "matin",
    "midi",
    "soir",
    "aprem",
    "prochain",
    "prochaine",
}
_JOIN = " et "
# « pas de coloration »
_NEG_WORDS = {"pas", "sans", "jamais", "ni"}
_NEG_WINDOW = 2


def plain(text: str) -> str:
    """minuscules sans accents."""
    t = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(c for c in t if not unicodedata.combining(c))


def _word_ok(word: str) -> bool:
    """un mot de prestation ?"""
    if len(word) < 3 or not word.isalpha():
        return False
    for stem in SERVICE_STEMS:
        if " " in stem:
            continue
        # meches, brushin
        if word.startswith(stem) or (len(word) >= 5 and stem.startswith(word)):
            return True
        # balyage -> balayage
        if (
            len(word) >= 6
            and len(stem) >= 5
            and SequenceMatcher(None, word, stem).ratio() >= FUZZY_MIN
        ):
            return True
    return False


def looks_like_service(span: str) -> bool:
    """le span ressemble à une prestation."""
    p = plain(span)
    if any(" " in s and s in p for s in SERVICE_STEMS):
        return True
    return any(_word_ok(w) for w in re.findall(r"[a-z]+", p))


def negated(tokens: list[str], start: int) -> bool:
    """prestation refusée juste avant ?"""
    for tok in reversed(tokens[max(0, start - _NEG_WINDOW) : start]):
        word = plain(tok)
        # la phrase d'avant compte pas
        if word.endswith((",", ".", "!", "?", ";")):
            return False
        if word in _NEG_WORDS:
            return True
    return False


def clean_service(span: str) -> str:
    """retire jours et heures en fin."""
    words = span.split()
    while words:
        last = plain(words[-1]).strip(".,;:!?…")
        # « coupe sans », « coupe mardi »
        drop = last in _WHEN_WORDS or last in _NEG_WORDS
        if drop or any(c.isdigit() for c in last) or not last:
            words.pop()
            continue
        break
    return " ".join(words).strip(" .,;:!?…")


class GuardedNERPredictor(NERPredictor):
    """ner + filtre sur la prestation."""

    def predict(self, text: str) -> dict[str, str]:
        """entités, prestations vérifiées."""
        pairs = self.predict_with_tags(text)
        tokens = [t for t, _ in pairs]
        entities: dict[str, str] = {}
        services: list[str] = []
        cur: str | None = None
        toks: list[str] = []
        start = 0
        for i, (token, tag) in enumerate([*pairs, ("", "O")]):
            if tag.startswith("I-") and cur == tag[2:]:
                toks.append(token)
                continue
            if cur and toks:
                key, value = cur.lower(), " ".join(toks)
                if key != "service":
                    # dernier gagne, comme avant
                    entities[key] = value
                elif not negated(tokens, start):
                    services.append(value)
            cur, toks, start = (tag[2:], [token], i) if tag.startswith("B-") else (None, [], i)
        # toutes les prestations, pas la dernière
        kept: list[str] = []
        for span in services:
            value = clean_service(span)
            if value and looks_like_service(value) and plain(value) not in map(plain, kept):
                kept.append(value)
        if kept:
            entities["service"] = _JOIN.join(kept)
        return entities
