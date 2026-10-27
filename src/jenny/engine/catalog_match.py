"""Repère les prestations du catalogue dans un message."""

from __future__ import annotations

import re
import unicodedata

# mots qui ne comptent pas
_STOP = frozenset(
    [
        "un",
        "une",
        "des",
        "de",
        "du",
        "la",
        "le",
        "les",
        "pour",
        "avec",
        "et",
        "d",
        "l",
        "en",
        "a",
        "au",
        "aux",
        "mon",
        "ma",
        "mes",
        "votre",
        "vos",
        "sur",
        "chez",
        "par",
        "juste",
        "simple",
        "petit",
        "petite",
    ]
)
# façons courantes de dire
_SYN = {
    "couleur": "coloration",
    "colo": "coloration",
    "teinture": "coloration",
    "brush": "brushing",
    "mec": "homme",
    "garcon": "homme",
    "masculin": "homme",
    "monsieur": "homme",
    "dame": "femme",
    "fille": "femme",
    "feminin": "femme",
    "madame": "femme",
}
_WORD_RE = re.compile(r"[a-z]+")
_MAX_CHARS = 2000


def _norm(s: str) -> str:
    """Minuscule sans accents."""
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _stem(w: str) -> str:
    """Pluriel simple retiré."""
    if len(w) > 3 and w[-1] in "sx":
        w = w[:-1]
    return _SYN.get(w, w)


def tokens(text: str) -> list[str]:
    """Mots utiles, normalisés."""
    words = _WORD_RE.findall(_norm(text[:_MAX_CHARS]))
    return [_stem(w) for w in words if w not in _STOP]


def _close(a: str, b: str) -> bool:
    """Égal ou une faute près."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    # distance d'édition <= 1
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        # deux lettres inversées
        i = diff[0] if len(diff) == 2 else -1
        return i >= 0 and diff[1] == i + 1 and a[i] == b[i + 1] and a[i + 1] == b[i]
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1 :]


def _has(words: list[str], tok: str) -> bool:
    return any(_close(w, tok) for w in words)


def find_services(message: str, services: list[str]) -> list[str]:
    """Prestations citées, ordre du catalogue."""
    if not message or not services:
        return []
    words = tokens(message)
    if not words:
        return []
    keyed = [(svc, tokens(svc)) for svc in services]
    keyed = [(svc, toks) for svc, toks in keyed if toks]
    full = [svc for svc, toks in keyed if all(_has(words, t) for t in toks)]
    # « coupe femme » couvre « coupe »
    heads_done = {toks[0] for svc, toks in keyed if svc in full}
    out = list(full)
    # mot de tête seul : seulement si unique
    by_head: dict[str, list[str]] = {}
    for svc, toks in keyed:
        by_head.setdefault(toks[0], []).append(svc)
    for head, svcs in by_head.items():
        if head in heads_done or len(svcs) != 1 or svcs[0] in out:
            continue
        if _has(words, head):
            out.append(svcs[0])
    order = {svc: i for i, svc in enumerate(services)}
    return sorted(out, key=order.__getitem__)


def ambiguous_heads(message: str, services: list[str]) -> list[str]:
    """« une coupe » : femme ou homme ?"""
    words = tokens(message or "")
    by_head: dict[str, list[str]] = {}
    for svc in services:
        toks = tokens(svc)
        if toks:
            by_head.setdefault(toks[0], []).append(svc)
    found = set(find_services(message, services))
    return [
        svc
        for head, svcs in by_head.items()
        if len(svcs) > 1 and _has(words, head) and not found & set(svcs)
        for svc in svcs
    ]
