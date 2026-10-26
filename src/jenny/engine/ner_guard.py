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
# mots vides des noms
_FILLERS = {"une", "des", "les", "pour", "avec", "mon", "mes", "son", "ses"}


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
            # « nombre » n'est pas « ombre »
            and word[0] == stem[0]
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


def _same_word(word: str, ref: str) -> bool:
    """même mot, préfixe ou faute."""
    w, r = word.rstrip("sx"), ref.rstrip("sx")
    if w == r or (len(w) >= 4 and r.startswith(w)):
        return True
    # balyage -> balayage
    return len(w) >= 6 and w[0] == r[0] and SequenceMatcher(None, w, r).ratio() >= FUZZY_MIN


def _keywords(text: str) -> list[str]:
    """mots utiles d'un nom."""
    return [w for w in re.findall(r"[a-z]+", plain(text)) if len(w) > 2 and w not in _FILLERS]


def _covers(words: list[str], refs: list[str]) -> bool:
    """chaque mot trouvé en face."""
    return bool(words) and all(any(_same_word(w, r) for r in refs) for w in words)


def _one_service(part: str, catalog: list[str]) -> str | None:
    """une presta du catalogue, sinon rien."""
    words = _keywords(part)
    named = [(n, _keywords(n)) for n in catalog]
    # nom du catalogue cité en entier
    full = [(n, k) for n, k in named if _covers(k, words)]
    if full:
        top = max(len(k) for _, k in full)
        full = [n for n, k in full if len(k) == top]
        return full[0] if len(full) == 1 else None
    # « colo », « soin » : un seul candidat
    part_of = [n for n, k in named if _covers(words, k)]
    return part_of[0] if len(part_of) == 1 else None


def catalog_service(value: str | None, catalog: list[str] | None) -> str | None:
    """presta du ner, si le catalogue la connaît."""
    if not value or not catalog:
        return None
    found: list[str] = []
    for part in plain(value).split(_JOIN):
        name = _one_service(part, catalog)
        # inconnue ou ambiguë : on demande
        if name is None:
            return None
        if name not in found:
            found.append(name)
    return _JOIN.join(found) if found else None


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
