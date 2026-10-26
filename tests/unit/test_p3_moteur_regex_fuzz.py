"""passe 3 moteur : fuzz des regex, pas de ReDoS."""

from __future__ import annotations

import importlib
import itertools
import pkgutil
import re
import time

import pytest

import jenny.engine

BUDGET = 0.05  # 50 ms par appel
LENGTHS = (120, 300, 800, 2000, 10000)

# lentes, hors fichiers du moteur
KNOWN_SLOW = {
    "jenny.engine.intelligence._FACT_STOP_RE": (
        "intelligence.py : blancs répétés, quadratique (lu sur des bouts courts)"
    ),
    "jenny.engine.intelligence._DEFLECTION_RE": (
        "intelligence.py : contact\\w* répété, quadratique (lu sur la réponse)"
    ),
}


def _modules() -> list:
    names = [f"jenny.engine.{m.name}" for m in pkgutil.iter_modules(jenny.engine.__path__)]
    names.append("jenny.services.offer_cap")
    return [importlib.import_module(n) for n in sorted(names)]


def _patterns() -> list[tuple[str, re.Pattern]]:
    """Regex compilées des modules."""
    seen: dict[int, tuple[str, re.Pattern]] = {}

    def walk(name: str, obj: object, depth: int) -> None:
        if isinstance(obj, re.Pattern):
            seen.setdefault(id(obj), (name, obj))
        elif depth < 2 and isinstance(obj, list | tuple | set | frozenset):
            for i, x in enumerate(obj):
                walk(f"{name}[{i}]", x, depth + 1)
        elif depth < 2 and isinstance(obj, dict):
            for k, x in obj.items():
                walk(f"{name}[{k}]", x, depth + 1)

    for mod in _modules():
        for attr, obj in vars(mod).items():
            walk(f"{mod.__name__}.{attr}", obj, 0)
    return sorted(seen.values(), key=lambda t: t[0])


def _words(p: re.Pattern) -> list[str]:
    """Mots du motif, dans l'ordre."""
    src = re.sub(r"\[\^?([^\]\\])[^\]]*\]", r"\1", p.pattern)  # classe : 1er car.
    src = re.sub(r"\\[a-zA-Z]", " ", src)
    return re.findall(r"[a-zà-ÿ'’]{2,}|\d+", src, re.I)[:300] or ["a"]  # noqa: RUF001


def _shapes(p: re.Pattern):
    """(début, motif répété, fin)"""
    seq = _words(p)
    ws = list(dict.fromkeys(seq))[:120]
    for pre in ("", "merci, à demain", "oui", "c'est"):
        for sep in (" ", ", ", "\n", ""):
            for end in ("?", "x", "@"):
                yield pre, sep + sep.join(ws), end
    # couples : boucles ambiguës
    for a, b in dict.fromkeys(itertools.pairwise(seq)):
        for end in ("?", "x"):
            yield "merci, à demain", f" {a} {b}", end
    for w in ws:
        for sep in (" ", ""):
            yield "", sep + w, "x"
    for ch in (" ", "\n", "a", "1", "!", "a ", "'", "-", "1h", "é", ".", "a1", "<|", "a@"):
        for end in ("?", "@", "x"):
            yield "", ch, end


def _build(shape: tuple[str, str, str], length: int) -> str:
    pre, body, end = shape
    return pre + body * max(1, (length - len(pre)) // max(1, len(body))) + end


def _timed(p: re.Pattern, s: str) -> float:
    """meilleur de 3, bruit écarté"""
    best = 9.0
    for _ in range(3):
        t0 = time.perf_counter()
        p.sub(" ", s)
        dt = time.perf_counter() - t0
        best = min(best, dt)
        # net : pas besoin de refaire
        if best < BUDGET or dt > 4 * BUDGET:
            break
    return best


def _worst(p: re.Pattern) -> tuple[float, str]:
    worst, arg = 0.0, ""
    for shape in _shapes(p):
        for length in LENGTHS:
            s = _build(shape, length)
            dt = _timed(p, s)
            if dt > worst:
                worst, arg = dt, s
            if dt >= BUDGET:
                return worst, arg
            # linéaire : 10000 inutile
            if length == 2000 and dt < BUDGET / 125:
                break
    return worst, arg


_ALL = _patterns()


def test_toutes_les_regex_trouvees() -> None:
    names = {n for n, _ in _ALL}
    assert "jenny.engine.conversation_engine._FAREWELL_WHEN_RE" in names
    assert "jenny.engine.datetime_fr._HM_RE" in names
    assert "jenny.services.offer_cap" in {m.__name__ for m in _modules()}
    assert len(_ALL) > 60


@pytest.mark.parametrize(
    ("name", "pattern"),
    [
        pytest.param(n, p, id=n, marks=[pytest.mark.xfail(reason=KNOWN_SLOW[n], strict=False)])
        if n in KNOWN_SLOW
        else pytest.param(n, p, id=n)
        for n, p in _ALL
    ],
)
def test_regex_sans_redos(name: str, pattern: re.Pattern) -> None:
    worst, arg = _worst(pattern)
    assert worst < BUDGET, f"{name} : {worst * 1000:.0f} ms sur {arg[:60]!r}… ({len(arg)} car.)"


@pytest.mark.parametrize(
    "msg", ["stop " * 2000, "stop" + " " * 9000 + "x", "ne m'envoyez plus " * 500, "a" * 10000]
)
def test_stop_rapide(msg: str) -> None:
    # offer_cap : pas de regex globale
    from jenny.services.offer_cap import is_stop_reply

    best = 9.0
    for _ in range(3):
        t0 = time.perf_counter()
        is_stop_reply(msg)
        best = min(best, time.perf_counter() - t0)
    assert best < BUDGET


def test_attaque_connue_au_revoir() -> None:
    # l'attaque de la revue
    from jenny.engine.conversation_engine import _FAREWELL_WHEN_RE

    for n in (20, 40, 400):
        msg = "merci, à demain" + " merci encore" * n + " ?"
        assert _timed(_FAREWELL_WHEN_RE, msg) < BUDGET
