"""bruit de surface façon client."""

from __future__ import annotations

import random
import re
import unicodedata
import zlib

# abréviations sms du train
TRAIN_SMS: tuple[tuple[str, str], ...] = (
    (r"rendez[- ]vous", "rdv"),
    (r"s'il vous pla[iî]t", "svp"),
    (r"bonjour", "bjr"),
    (r"merci", "mrc"),
    (r"pour", "pr"),
    (r"combien", "cbien"),
)
_TRAIN_SMS_RE = [(re.compile(rf"\b{pat}\b", re.I), court) for pat, court in TRAIN_SMS]

# perturbation de l'éval
EVAL_SMS = {
    "rendez-vous": "rdv",
    "s'il vous plaît": "svp",
    "bonjour": "bjr",
    "merci": "mrc",
    "pour": "pr",
    "combien": "cbien",
}

# formes jamais vues au train
UNSEEN_SMS: tuple[tuple[str, str], ...] = (
    (r"qu'est[- ]ce que", "keske"),
    (r"est[- ]ce que", "esk"),
    (r"je voudrais", "jvoudrais"),
    (r"je veux", "jveux"),
    (r"je peux", "jpeux"),
    (r"je suis", "jsuis"),
    (r"aujourd'hui", "ajd"),
    (r"s'il te pla[iî]t", "stp"),
    (r"c'est", "c"),
    (r"vous", "vs"),
    (r"quand", "qd"),
    (r"demain", "dmn"),
    (r"beaucoup", "bcp"),
    (r"quelles?|quels?", "kel"),
    (r"salut", "slt"),
    (r"toujours", "tjrs"),
    (r"disponibles?", "dispo"),
    (r"pourquoi", "pk"),
    (r"parce que", "pcq"),
    (r"avec", "avc"),
    (r"dans", "ds"),
    (r"tout", "tt"),
    (r"bien", "b1"),
)
_UNSEEN_RE = [(re.compile(rf"\b(?:{pat})\b", re.I), court) for pat, court in UNSEEN_SMS]

# voisins clavier azerty
_VOISINS = {
    "a": "zq",
    "z": "aes",
    "e": "zrd",
    "r": "etf",
    "t": "ryg",
    "y": "tuh",
    "u": "yij",
    "i": "uok",
    "o": "ipl",
    "p": "om",
    "q": "asw",
    "s": "qdz",
    "d": "sfe",
    "f": "dgr",
    "g": "fht",
    "h": "gjy",
    "j": "hku",
    "k": "jli",
    "l": "kmo",
    "m": "lp",
    "w": "xq",
    "x": "wc",
    "c": "xv",
    "v": "cb",
    "b": "vn",
    "n": "bm",
}


def strip_accents(text: str) -> str:
    """retire les accents."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def strip_punct(text: str) -> str:
    """retire la ponctuation."""
    out = re.sub(r"[^\w\s'-]", " ", text)
    return " ".join(out.split())


def plain(text: str) -> str:
    """minuscules, sans accents ni ponctuation."""
    return strip_punct(strip_accents(text.lower()))


def sms(text: str) -> str:
    """abréviations sms du train."""
    out = text
    for pat, court in _TRAIN_SMS_RE:
        out = pat.sub(court, out)
    return out


def typo(text: str, rng: random.Random) -> str:
    """une ou deux fautes légères."""
    words = text.split()
    cands = [i for i, w in enumerate(words) if len(w) >= 4 and w.isalpha()]
    if not cands:
        return text
    n = 2 if len(words) > 8 else 1
    for i in rng.sample(cands, min(n, len(cands))):
        w = words[i]
        j = rng.randrange(1, len(w) - 1)
        op = rng.randrange(4)
        if op == 0:
            # lettre oubliée
            w = w[:j] + w[j + 1 :]
        elif op == 1:
            # lettres inversées
            w = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
        elif op == 2:
            # lettre doublée
            w = w[:j] + w[j] + w[j:]
        else:
            # touche voisine
            voisins = _VOISINS.get(w[j].lower())
            if voisins:
                w = w[:j] + rng.choice(voisins) + w[j + 1 :]
        words[i] = w
    return " ".join(words)


def variants(text: str) -> list[str]:
    """variantes déterministes d'un texte."""
    rng = random.Random(zlib.crc32(text.encode("utf-8")))
    base = plain(text)
    court = sms(base)
    out = [text, base, court, typo(court, rng)]
    # garde l'ordre, sans doublon
    seen: set[str] = set()
    uniq = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def perturb_eval(text: str) -> str:
    """perturbation de référence (éval)."""
    out = text.lower()
    for long, court in EVAL_SMS.items():
        out = out.replace(long, court)
    out = "".join(c for c in unicodedata.normalize("NFD", out) if not unicodedata.combining(c))
    return re.sub(r"[^\w\s'-]", "", out)


def perturb_unseen(text: str) -> str:
    """sms inédit, jamais vu au train."""
    out = strip_accents(text.lower())
    out = out.replace("’", "'")  # noqa: RUF001
    for pat, court in _UNSEEN_RE:
        out = pat.sub(court, out)
    # apostrophes collées : j'ai -> jai
    out = re.sub(r"(\w)'(\w)", r"\1\2", out)
    out = re.sub(r"[^\w\s]", " ", out)
    return " ".join(out.split())
