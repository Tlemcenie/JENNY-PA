"""Mesure HONNÊTE des modèles intention (LSTM, tête mpnet) et NER (BiGRU).

L'ancienne version tirait 600 lignes du fichier COMPLET, donc ~70 % du
« test » était en fait du train (le split d'entraînement est un
``random_split`` sur ce même fichier) → chiffres gonflés d'environ 5 points.

Ici on reproduit le split exact de l'entraînement (seed 42, 70/15/15) et on
n'évalue que sur le TEST. Les deux modèles d'intention passent sur le MÊME
test, le MÊME test perturbé (sans accents / sans ponctuation / SMS) et un
test « SMS inédit » dont les formes ne sont jamais vues à l'entraînement.
On mesure aussi la latence par message (appel unitaire, comme le moteur).

Usage : PYTHONPATH=src:. .venv/bin/python scripts/eval_ml_models.py
        [--skip-ner] [--skip-train] [--skip-cpu] [--latency-n 200]
"""

import argparse
import json
import platform
import statistics
import time
from collections import defaultdict
from pathlib import Path

import torch
from torch.utils.data import random_split

from ml.models.intent_head.augment import perturb_eval as perturb
from ml.models.intent_head.augment import perturb_unseen

SEED = 42
OUT = Path("var/eval/ml_metrics.json")
LSTM_PATH = "checkpoints/intent/best_model.pt"
HEAD_PATH = "checkpoints/intent_head/head.joblib"
NER_PATH = "checkpoints/ner/best_model.pt"


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


def spans(tokens: list[str], tags: list[str]) -> set[tuple[str, int, int]]:
    """Spans BIO -> {(type, debut, fin)} pour un F1 strict."""
    found: set[tuple[str, int, int]] = set()
    cur_type, start = None, 0
    for i, tag in enumerate([*tags, "O"]):
        if tag.startswith("B-") or tag == "O" or (tag.startswith("I-") and tag[2:] != cur_type):
            if cur_type is not None:
                found.add((cur_type, start, i))
                cur_type = None
            if tag.startswith("B-"):
                cur_type, start = tag[2:], i
        elif tag.startswith("I-") and tag[2:] == cur_type:
            continue
    return found


def gold_labels(row: dict) -> list[str]:
    return list(row.get("intents") or ["general"])


def latency_ms(fn, texts: list[str]) -> dict:
    """Latence d'un appel unitaire (ms), après chauffe."""
    for t in texts[:5]:
        fn(t)
    durees = []
    for t in texts:
        t0 = time.perf_counter()
        fn(t)
        durees.append(1000 * (time.perf_counter() - t0))
    durees.sort()
    return {
        "n": len(durees),
        "moyenne": round(statistics.fmean(durees), 2),
        "p50": round(durees[len(durees) // 2], 2),
        "p95": round(durees[int(0.95 * (len(durees) - 1))], 2),
    }


def score_intent(predictor, rows: list[dict], idx: dict, with_train: bool) -> dict:
    """Top-1, macro-F1, multi-intention, clarif sur le split test."""
    res: dict = {}
    vues = [("test", lambda t: t), ("test_perturbe", perturb), ("test_sms_inedit", perturb_unseen)]
    if with_train:
        vues.insert(0, ("train", lambda t: t))
    for nom, f in vues:
        part = idx["train" if nom == "train" else "test"]
        gold = [gold_labels(rows[i]) for i in part]
        preds = predictor.predict_batch_multi([f(rows[i]["text"]) for i in part])
        pairs = [(g[0], p.get("primary_intent") or "?") for g, p in zip(gold, preds, strict=True)]
        acc = 100 * sum(v == pr for v, pr in pairs) / len(pairs)
        mf1, detail = macro_f1(pairs)
        res[nom] = {"n": len(pairs), "top1": round(acc, 1), "macro_f1": round(mf1, 1)}
        if nom == "test":
            res["par_classe"] = dict(sorted(detail.items(), key=lambda kv: kv[1]["f1"]))
            # multi-intention et clarif
            set_f1 = faux = single = clarif = 0.0
            for g, p in zip(gold, preds, strict=True):
                ps = {d["intent"] for d in p["intents"]}
                gs = set(g)
                set_f1 += 2 * len(ps & gs) / (len(ps) + len(gs))
                if len(gs) == 1:
                    single += 1
                    faux += p["is_multi_intent"]
                clarif += bool(p["needs_clarification"])
            res["multi"] = {
                "set_f1": round(100 * set_f1 / len(gold), 1),
                "faux_multi_pct": round(100 * faux / max(single, 1), 1),
                "clarif_pct": round(100 * clarif / len(gold), 1),
            }
    res["chute_robustesse_pts"] = round(res["test"]["top1"] - res["test_perturbe"]["top1"], 1)
    return res


def eval_intents(with_train: bool, cpu_latency: bool, latency_n: int) -> dict:
    from ml.models.intent.predict import IntentPredictor
    from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor, get_encoder

    rows = load_jsonl("data/generated/intents.jsonl")
    idx = split_indices(len(rows))
    sample = [rows[i]["text"] for i in idx["test"][:latency_n]]
    out: dict = {"n_total": len(rows)}

    lstm = IntentPredictor.from_checkpoint(LSTM_PATH)
    res = score_intent(lstm, rows, idx, with_train)
    res["latence_ms"] = {lstm.config.device: latency_ms(lstm.predict_multi, sample)}
    if cpu_latency and lstm.config.device != "cpu":
        lstm.model.to("cpu")
        lstm.config.device = "cpu"
        res["latence_ms"]["cpu"] = latency_ms(lstm.predict_multi, sample)
    out["intent_lstm"] = res

    head = EmbeddingIntentPredictor.from_checkpoint(HEAD_PATH)
    res = score_intent(head, rows, idx, with_train)
    device = str(head.encoder.device).split(":")[0]
    res["latence_ms"] = {device: latency_ms(head.predict_multi, sample)}
    if cpu_latency and device != "cpu":
        head_cpu = EmbeddingIntentPredictor.from_checkpoint(
            HEAD_PATH, encoder=get_encoder(ENCODER_NAME, device="cpu")
        )
        res["latence_ms"]["cpu"] = latency_ms(head_cpu.predict_multi, sample)
    res["checkpoint"] = {k: head.meta.get(k) for k in ("alpha", "C", "temperature")}
    res["checkpoint"]["multi_threshold"] = head.multi_threshold
    out["intent_head"] = res

    a, b = out["intent_lstm"], out["intent_head"]
    comp = {}
    for nom in ("test", "test_perturbe", "test_sms_inedit"):
        comp[nom] = {
            "lstm_top1": a[nom]["top1"],
            "head_top1": b[nom]["top1"],
            "delta_pts": round(b[nom]["top1"] - a[nom]["top1"], 1),
            "lstm_macro_f1": a[nom]["macro_f1"],
            "head_macro_f1": b[nom]["macro_f1"],
        }
    comp["head_bat_lstm_test"] = b["test"]["top1"] > a["test"]["top1"]
    comp["head_bat_lstm_perturbe"] = b["test_perturbe"]["top1"] > a["test_perturbe"]["top1"]
    out["comparaison"] = comp
    return out


def eval_ner(with_train: bool, cpu_latency: bool, latency_n: int) -> dict:
    from ml.models.ner.predict import NERPredictor

    p = NERPredictor.from_checkpoint(NER_PATH)
    rows = load_jsonl("data/generated/ner.jsonl")
    idx = split_indices(len(rows))

    res: dict = {"n_total": len(rows)}
    for nom in ("train", "test") if with_train else ("test",):
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
    sample = [rows[i]["text"] for i in idx["test"][:latency_n]]
    res["latence_ms"] = {p.config.device: latency_ms(p.predict, sample)}
    if cpu_latency and p.config.device != "cpu":
        p.model.to("cpu")
        p.config.device = "cpu"
        res["latence_ms"]["cpu"] = latency_ms(p.predict, sample)
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="éval honnête des modèles ML")
    parser.add_argument("--skip-ner", action="store_true")
    parser.add_argument("--skip-train", action="store_true", help="pas d'éval sur le train")
    parser.add_argument("--skip-cpu", action="store_true", help="pas de latence CPU")
    parser.add_argument("--latency-n", type=int, default=200)
    args = parser.parse_args()

    out: dict = {
        "note": "Évalué sur le SPLIT TEST uniquement (seed 42, 70/15/15). "
        "L'écart train/test mesure la mémorisation. test_perturbe = minuscules, "
        "sans accents ni ponctuation, rdv/svp/bjr/mrc/pr/cbien ; test_sms_inedit = "
        "abréviations jamais vues à l'entraînement (jvoudrais, vs, esk, qd...). "
        "Latence = un appel predict_multi par message, comme le moteur.",
        "machine": {"python": platform.python_version(), "torch": torch.__version__},
    }
    out.update(eval_intents(not args.skip_train, not args.skip_cpu, args.latency_n))
    if not args.skip_ner:
        out["ner_bigru"] = eval_ner(not args.skip_train, not args.skip_cpu, args.latency_n)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
