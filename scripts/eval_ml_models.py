"""Mesure HONNÊTE des modèles intention (LSTM) et NER (BiGRU).

L'ancienne version tirait 600 lignes du fichier COMPLET, donc ~70 % du
« test » était en fait du train (le split d'entraînement est un
``random_split`` sur ce même fichier) → chiffres gonflés d'environ 5 points.

Ici on reproduit le split exact de l'entraînement (seed 42, 70/15/15) et on
n'évalue que sur le TEST. On affiche aussi le TRAIN pour voir la mémorisation,
et un test de robustesse (sans accents / sans ponctuation / SMS) parce que
c'est là que ces modèles cassent vraiment.

Usage : PYTHONPATH=src:. .venv/bin/python scripts/eval_ml_models.py
"""

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import torch
from torch.utils.data import random_split

SEED = 42
OUT = Path("var/eval/ml_metrics.json")


def load_jsonl(path: str) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(ligne) for ligne in lines if ligne.strip()]


def split_indices(total: int) -> dict[str, list[int]]:
    """Même découpage que l'entraînement (sinon on retombe dans la fuite)."""
    train_size = int(0.70 * total)
    val_size = int(0.15 * total)
    test_size = total - train_size - val_size
    gen = torch.Generator().manual_seed(SEED)
    tr, va, te = random_split(range(total), [train_size, val_size, test_size], generator=gen)
    return {"train": list(tr.indices), "val": list(va.indices), "test": list(te.indices)}


def macro_f1(pairs: list[tuple[str, str]]) -> tuple[float, dict]:
    """macro-F1 + détail par classe."""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for vrai, pred in pairs:
        if vrai == pred:
            tp[vrai] += 1
        else:
            fp[pred] += 1
            fn[vrai] += 1
    classes = set(tp) | set(fp) | set(fn)
    detail, total = {}, 0.0
    for c in classes:
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        detail[c] = {"f1": round(100 * f1, 1), "support": tp[c] + fn[c]}
        total += f1
    return (100 * total / len(classes) if classes else 0.0), detail


# ── perturbations réalistes (SMS, fautes, sans accents) ──
_SMS = {
    "rendez-vous": "rdv",
    "s'il vous plaît": "svp",
    "bonjour": "bjr",
    "merci": "mrc",
    "pour": "pr",
    "combien": "cbien",
}


def perturb(text: str) -> str:
    out = text.lower()
    for long, court in _SMS.items():
        out = out.replace(long, court)
    out = "".join(c for c in unicodedata.normalize("NFD", out) if not unicodedata.combining(c))
    return re.sub(r"[^\w\s'-]", "", out)


def spans(tokens: list[str], tags: list[str]) -> set[tuple[str, int, int]]:
    """Spans BIO -> {(type, debut, fin)} pour un F1 strict."""
    found: set[tuple[str, int, int]] = set()
    cur_type, start = None, 0
    for i, tag in enumerate(list(tags) + ["O"]):
        if tag.startswith("B-") or tag == "O" or (tag.startswith("I-") and tag[2:] != cur_type):
            if cur_type is not None:
                found.add((cur_type, start, i))
                cur_type = None
            if tag.startswith("B-"):
                cur_type, start = tag[2:], i
        elif tag.startswith("I-") and tag[2:] == cur_type:
            continue
    return found


def eval_intent() -> dict:
    from ml.models.intent.predict import IntentPredictor

    p = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")
    rows = load_jsonl("data/generated/intents.jsonl")
    idx = split_indices(len(rows))

    res: dict = {"n_total": len(rows)}
    for nom in ("train", "test"):
        pairs = []
        for i in idx[nom]:
            r = rows[i]
            vrai = (r.get("intents") or ["general"])[0]
            pred = p.predict_multi(r["text"]).get("primary_intent") or "?"
            pairs.append((vrai, pred))
        acc = 100 * sum(v == pr for v, pr in pairs) / len(pairs)
        mf1, detail = macro_f1(pairs)
        res[nom] = {"n": len(pairs), "top1": round(acc, 1), "macro_f1": round(mf1, 1)}
        if nom == "test":
            res["par_classe"] = dict(sorted(detail.items(), key=lambda kv: kv[1]["f1"]))

    # robustesse : même test, écrit comme un vrai client
    pairs = []
    for i in idx["test"]:
        r = rows[i]
        vrai = (r.get("intents") or ["general"])[0]
        pred = p.predict_multi(perturb(r["text"])).get("primary_intent") or "?"
        pairs.append((vrai, pred))
    acc_rob = 100 * sum(v == pr for v, pr in pairs) / len(pairs)
    res["test_perturbe"] = {"top1": round(acc_rob, 1)}
    res["chute_robustesse_pts"] = round(res["test"]["top1"] - acc_rob, 1)
    return res


def eval_ner() -> dict:
    from ml.models.ner.predict import NERPredictor

    p = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")
    rows = load_jsonl("data/generated/ner.jsonl")
    idx = split_indices(len(rows))

    res: dict = {"n_total": len(rows)}
    for nom in ("train", "test"):
        tp = fp = fn = tok_ok = tok_tot = 0
        for i in idx[nom]:
            r = rows[i]
            toks = r.get("tokens") or r["text"].split()
            gold_tags = r.get("tags") or []
            pred = p.predict_with_tags(r["text"])
            pred_tags = [t for _, t in pred][: len(toks)]
            pred_tags += ["O"] * (len(toks) - len(pred_tags))
            g, d = spans(toks, gold_tags), spans(toks, pred_tags)
            tp += len(g & d)
            fp += len(d - g)
            fn += len(g - d)
            for a, b in zip(gold_tags, pred_tags, strict=False):
                tok_tot += 1
                tok_ok += a == b
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        res[nom] = {
            "n": len(idx[nom]),
            "span_f1": round(100 * f1, 1),
            "token_acc": round(100 * tok_ok / tok_tot, 1) if tok_tot else 0.0,
        }
    return res


def main() -> None:
    out = {
        "note": "Évalué sur le SPLIT TEST uniquement (seed 42, 70/15/15). "
        "L'écart train/test mesure la mémorisation.",
        "intent_lstm": eval_intent(),
        "ner_bigru": eval_ner(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
