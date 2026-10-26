"""slots service / date / heure, avec et sans NER.

Rejoue des conversations dans le vrai moteur (tête d'intention, sans LLM,
ni actions, ni base) et note les slots posés à chaque tour. Trois passes :
NER servi (filtre prestation), NER brut, NER coupé (regex + catalogue).

- parcours de tests/e2e/test_user_coiffeur.py (catalogue seed-coiffeur),
  notés contre data/generated/ner_slots_gold.jsonl, annoté à la main ;
- --live URL : messages entrants de la base, en lecture seule. Pas de gold :
  on compte et on liste les écarts (--show-diffs, sur stderr seulement).

Usage : PYTHONPATH=src:. .venv/bin/python scripts/eval_ner_slots.py
        [--live postgresql://...] [--show-diffs]
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import os
import re
import sys
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from collections.abc import Iterator

if __name__ == "__main__":
    # états en mémoire seulement
    os.environ["JENNY_REDIS_URL"] = ""

from jenny.engine import factory
from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
from jenny.engine.datetime_fr import parse_fr_date, parse_fr_time, today_in
from jenny.engine.ner_guard import looks_like_service
from jenny.engine.state_manager import ConversationState, StateManager
from jenny.rag.kb_coiffeur import DEFAULT_COIFFEUR

SCENARIOS = Path("tests/e2e/test_user_coiffeur.py")
GOLD = Path("data/generated/ner_slots_gold.jsonl")
OUT = Path("var/eval/ner_slots.json")
SLOTS = ("service", "date", "time")
# là où les slots servent
RDV_INTENTS = frozenset({"appointment", "manage_appointment", "planning"})
TZ = "Europe/Paris"
CATALOG = [c[0] for c in DEFAULT_COIFFEUR]

# slots posés pendant le tour
_TURN: list[tuple[str, str]] = []


@contextmanager
def spy_slots() -> Iterator[None]:
    """note chaque slot posé."""
    orig = ConversationState.set_slot

    def spy(self, name, value, *args, **kwargs):
        if name in SLOTS:
            _TURN.append((name, str(value)))
        return orig(self, name, value, *args, **kwargs)

    ConversationState.set_slot = spy
    try:
        yield
    finally:
        ConversationState.set_slot = orig


def plain(text: str) -> str:
    """minuscules sans accents."""
    t = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(c for c in t if not unicodedata.combining(c))


def scenario_messages(path: Path = SCENARIOS) -> list[list[str]]:
    """messages des tests, par parcours."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    convs = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef) or not fn.name.startswith(
            "test"
        ):
            continue
        found: dict[int, str] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                # _send(engine, conv, message)
                if name == "_send" and len(node.args) >= 3:
                    arg = node.args[2]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found[arg.lineno] = arg.value
                for kw in node.keywords:
                    v = kw.value
                    if kw.arg in ("message", "message_text") and isinstance(v, ast.Constant):
                        found[v.lineno] = v.value
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "message"
                        and isinstance(v, ast.Constant)
                    ):
                        found[v.lineno] = v.value
        msgs = [m for _, m in sorted(found.items()) if isinstance(m, str) and m.strip()]
        if msgs:
            convs.append(msgs)
    return convs


async def live_conversations(url: str) -> list[tuple[list[str], list[str]]]:
    """messages entrants, lecture seule."""
    import asyncpg

    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                "SELECT conversation_id, business_id, content_text FROM messages "
                "WHERE direction = 'inbound' ORDER BY conversation_id, created_at, id"
            )
            cats = await conn.fetch(
                "SELECT business_id, name FROM prestations "
                "WHERE coalesce(is_active, true) ORDER BY business_id, sort_order"
            )
    finally:
        await conn.close()
    catalog: dict[UUID, list[str]] = defaultdict(list)
    for r in cats:
        catalog[r["business_id"]].append(r["name"])
    convs: dict[UUID, tuple[list[str], list[str]]] = {}
    for r in rows:
        conv = convs.setdefault(r["conversation_id"], ([], catalog.get(r["business_id"]) or []))
        if (r["content_text"] or "").strip():
            conv[0].append(r["content_text"])
    return list(convs.values())


def build_engines() -> dict[str, ConversationEngine]:
    """même tête : ner servi, brut, aucun."""
    from ml.models.ner.predict import NERPredictor

    intent = factory.load_intent_predictor("head", fallback=False)
    if intent is None:
        raise SystemExit("tête d'intention indisponible")
    # ner servi : filtre prestation
    ner = factory.load_ner_predictor()
    if ner is None:
        raise SystemExit("ner indisponible")
    # même poids, sans filtre
    brut = NERPredictor(ner.model, ner.vocab, ner.config)
    return {
        name: ConversationEngine(
            state_manager=StateManager(), intent_predictor=intent, ner_predictor=n
        )
        for name, n in (("avec_ner", ner), ("ner_brut", brut), ("sans_ner", None))
    }


async def replay(
    engine: ConversationEngine, convs: list[tuple[list[str], list[str]]]
) -> list[list[dict]]:
    """rejoue, slots posés par tour."""
    out = []
    with spy_slots():
        for msgs, catalog in convs:
            conv_id, biz = uuid4(), uuid4()
            turns = []
            for text in msgs:
                _TURN.clear()
                r = await engine.process(
                    EngineRequest(
                        conversation_id=conv_id,
                        business_id=biz,
                        message_text=text,
                        channel="whatsapp",
                        catalog_services=catalog or None,
                        timezone=TZ,
                    )
                )
                # dernier posé gagne
                got = dict(_TURN)
                state = await engine.state_manager.aget(conv_id)
                known = {}
                for s in SLOTS:
                    slot = state.slots.get(s) if state is not None else None
                    if slot is not None and slot.filled and slot.value:
                        known[s] = str(slot.value)
                turns.append({"text": text, "intent": r.intent, "slots": got, "state": known})
            out.append(turns)
    return out


def load_gold(path: Path = GOLD) -> dict[str, dict]:
    """gold annoté à la main."""
    if not path.exists():
        return {}
    gold = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            gold[row["text"]] = row
    return gold


def judge(slot: str, value: str | None, gold: dict, seen_services: set[str]) -> str | None:
    """juste, faux, manque ou rien."""
    want = gold.get(slot)
    if slot == "service":
        want = [plain(w) for w in (want or [])]
        if value is None:
            return "manque" if want else None
        v = plain(value)
        # déjà cité plus tôt : contexte
        ok = [w for w in (*want, *seen_services) if w in v]
        return "juste" if ok else "faux"
    if value is None:
        return "manque" if want else None
    if not want:
        return "faux"
    today = today_in(TZ)
    if slot == "date":
        d = parse_fr_date(want, today=today)
        return "juste" if d and d.isoformat() == value else "faux"
    t = parse_fr_time(want) if ":" not in want else None
    expect = t.strftime("%H:%M") if t else want
    return "juste" if expect == value else "faux"


def score(
    runs: list[list[dict]], gold: dict[str, dict], intents: frozenset[str] | None = None
) -> dict:
    """rappel et précision par slot."""
    res: dict = {}
    for slot in SLOTS:
        c = defaultdict(int)
        for conv in runs:
            seen: set[str] = set()
            for turn in conv:
                g = gold.get(turn["text"])
                if g is None:
                    c["sans_gold"] += 1
                    continue
                if intents is not None and turn["intent"] not in intents:
                    seen.update(plain(s) for s in g.get("service") or [])
                    continue
                if g.get(slot):
                    c["attendus"] += 1
                value = turn["slots"].get(slot)
                if value is not None:
                    c["poses"] += 1
                verdict = judge(slot, value, g, seen)
                kept = turn.get("state", {}).get(slot)
                # déjà connu d'un tour d'avant
                if verdict == "manque" and kept and judge(slot, kept, g, seen) == "juste":
                    verdict = "juste"
                    c["garde"] += 1
                if verdict:
                    c[verdict] += 1
                seen.update(plain(s) for s in g.get("service") or [])
        att = c["attendus"]
        # précision : posés ce tour
        posed_ok = c["juste"] - c["garde"]
        res[slot] = {
            **dict(c),
            "rappel_pct": round(100 * c["juste"] / att, 1) if att else None,
            "precision_pct": round(100 * posed_ok / c["poses"], 1) if c["poses"] else None,
        }
    return res


def counts(runs: list[list[dict]]) -> dict:
    """slots posés et connus."""
    n = sum(len(c) for c in runs)
    out: dict = {"tours": n}
    for slot in SLOTS:
        out[slot] = {
            "poses": sum(t["slots"].get(slot) is not None for c in runs for t in c),
            "connus": sum(slot in t["state"] for c in runs for t in c),
        }
    return out


def words(value: str | None) -> set[str]:
    """mots, sans casse ni ponctuation."""
    return set(re.sub(r"[^\w ]", " ", plain(value or "")).split())


def gap_kind(a: str | None, b: str | None) -> str | None:
    """type d'écart, casse ignorée."""
    if a is None and b is None:
        return None
    if b is None:
        return "servi_seul"
    if a is None:
        return "autre_seul"
    wa, wb = words(a), words(b)
    if wa == wb:
        return None
    # « coupe femme mardi » / « Coupe femme »
    if wa <= wb or wb <= wa:
        return "meme_presta"
    return "differents"


def diffs(a: list[list[dict]], b: list[list[dict]], key: str = "slots") -> list[dict]:
    """tours où les slots diffèrent."""
    out = []
    for ca, cb in zip(a, b, strict=True):
        for ta, tb in zip(ca, cb, strict=True):
            d = {}
            for s in SLOTS:
                # posés ce tour, ou état
                va, vb = ta[key].get(s), tb[key].get(s)
                k = gap_kind(va, vb)
                if k:
                    d[s] = {"servi": va, "autre": vb, "type": k}
            if d:
                out.append({"text": ta["text"], "intent": ta["intent"], **d})
    return out


def gap_counts(ec: list[dict]) -> dict:
    """écarts par slot et par type."""
    out: dict = {s: defaultdict(int) for s in SLOTS}
    for d in ec:
        for s in SLOTS:
            if s in d:
                out[s][d[s]["type"]] += 1
    return {s: dict(v) for s, v in out.items()}


def suspects(runs: list[list[dict]]) -> int:
    """tours avec une prestation louche."""
    return sum(
        "service" in t["state"] and not looks_like_service(t["state"]["service"])
        for c in runs
        for t in c
    )


def gap_report(runs: dict[str, list[list[dict]]], label: str | None) -> dict:
    """écarts au ner servi."""
    out: dict = {"prestation_louche": {k: suspects(r) for k, r in runs.items()}}
    for other in ("sans_ner", "ner_brut"):
        for key, nom in (("slots", "poses"), ("state", "connus")):
            ec = diffs(runs["avec_ner"], runs[other], key)
            out[f"ecarts_{nom}_vs_{other}"] = {"tours": len(ec), **gap_counts(ec)}
            if label and key == "slots":
                for d in ec:
                    d["vs"] = other
                    print(label, json.dumps(d, ensure_ascii=False), file=sys.stderr)
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="slots avec et sans ner")
    parser.add_argument("--live", help="url postgres, lecture seule")
    parser.add_argument("--show-diffs", action="store_true", help="affiche les écarts")
    args = parser.parse_args()
    import structlog

    # logs du moteur coupés
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    engines = build_engines()
    gold = load_gold()
    report: dict = {"date_ref": today_in(TZ).isoformat(), "catalogue": CATALOG}

    convs = [(m, CATALOG) for m in scenario_messages()]
    runs = {k: await replay(e, convs) for k, e in engines.items()}
    report["coiffeur"] = {
        "parcours": len(convs),
        **{
            k: {
                "poses": counts(r),
                "score": score(r, gold),
                "score_flux_rdv": score(r, gold, RDV_INTENTS),
            }
            for k, r in runs.items()
        },
        **gap_report(runs, "coiffeur" if args.show_diffs else None),
    }
    missing = sorted({t["text"] for c in runs["avec_ner"] for t in c} - set(gold))
    report["coiffeur"]["sans_gold"] = missing

    if args.live:
        live = await live_conversations(args.live)
        runs_l = {k: await replay(e, live) for k, e in engines.items()}
        report["live"] = {
            "conversations": len(live),
            **{k: counts(r) for k, r in runs_l.items()},
            **gap_report(runs_l, "live" if args.show_diffs else None),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
