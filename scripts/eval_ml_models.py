"""Mesure HONNÊTE de la tête d'intention (mpnet + logistique).

Split figé seed 42, 70/15/15 : on note le TEST, le test perturbé (SMS,
sans accents) et des abréviations jamais vues. Latence par message.

Usage : PYTHONPATH=src:. .venv/bin/python scripts/eval_ml_models.py
        [--skip-train] [--skip-cpu] [--latency-n 200]
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
HEAD_PATH = "checkpoints/intent_head/head.npz"
# sonde manuelle hors gabarits
PROBE_PATH = Path("data/generated/intents_multi_probe.jsonl")


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


def multi_scores(gold: list[list[str]], preds: list[dict]) -> dict:
    """multi-intention : rappel, faux, set-f1."""
    set_f1 = faux = single = clarif = det = complet = hit = tot = n_multi = 0.0
    for g, p in zip(gold, preds, strict=True):
        ps = {d["intent"] for d in p["intents"]}
        gs = set(g)
        set_f1 += 2 * len(ps & gs) / (len(ps) + len(gs))
        if len(gs) == 1:
            single += 1
            faux += p["is_multi_intent"]
        else:
            n_multi += 1
            det += len(ps) > 1
            complet += gs <= ps
            hit += len(gs & ps)
            tot += len(gs)
        clarif += bool(p["needs_clarification"])
    return {
        "n_multi": int(n_multi),
        # au moins deux intentions
        "rappel_multi_pct": round(100 * det / max(n_multi, 1), 1),
        # les deux bonnes
        "multi_complet_pct": round(100 * complet / max(n_multi, 1), 1),
        "rappel_etiquettes_multi_pct": round(100 * hit / max(tot, 1), 1),
        "faux_multi_pct": round(100 * faux / max(single, 1), 1),
        "set_f1": round(100 * set_f1 / len(gold), 1),
        "clarif_pct": round(100 * clarif / len(gold), 1),
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
        if nom != "train":
            res[nom]["multi"] = multi_scores(gold, preds)
        if nom == "test":
            res["par_classe"] = dict(sorted(detail.items(), key=lambda kv: kv[1]["f1"]))
            res["multi"] = res[nom]["multi"]
    res["chute_robustesse_pts"] = round(res["test"]["top1"] - res["test_perturbe"]["top1"], 1)
    if PROBE_PATH.exists():
        probe = load_jsonl(str(PROBE_PATH))
        preds = predictor.predict_batch_multi([r["text"] for r in probe])
        gold = [gold_labels(r) for r in probe]
        res["sonde_multi"] = multi_scores(gold, preds)
        ok = sum(p["primary_intent"] in g for g, p in zip(gold, preds, strict=True))
        res["sonde_multi"]["top1_dans_gold_pct"] = round(100 * ok / len(probe), 1)
    return res


def softmax_only(head):
    """même tête, sans secondaires."""
    from ml.models.intent_head.predict import EmbeddingIntentPredictor

    # seuil softmax calé sur val
    t = head.meta.get("softmax_multi_threshold", 0.47)
    return EmbeddingIntentPredictor(
        head.encoder,
        head.coef,
        head.intercept,
        temperature=head.temperature,
        multi_threshold=t,
        max_intents=3,
        clarify_threshold=head.clarify_threshold,
        labels=head.labels,
        chars=head.chars,
        char_coef=head.char_coef,
    )


def eval_intents(with_train: bool, cpu_latency: bool, latency_n: int) -> dict:
    from ml.models.intent_head.predict import ENCODER_NAME, EmbeddingIntentPredictor, get_encoder

    rows = load_jsonl("data/generated/intents.jsonl")
    idx = split_indices(len(rows))
    sample = [rows[i]["text"] for i in idx["test"][:latency_n]]
    out: dict = {"n_total": len(rows)}

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
    res["checkpoint"]["secondaires"] = head.has_secondary
    out["intent_head"] = res

    # avant : softmax seule (passe 1)
    avant = softmax_only(head)
    out["intent_head_avant"] = score_intent(avant, rows, idx, False)
    out["intent_head_avant"]["multi_threshold"] = avant.multi_threshold

    # secondaires : top-1 inchangé ?
    out["top1_identique_avant"] = {
        nom: out["intent_head_avant"][nom]["top1"] == out["intent_head"][nom]["top1"]
        for nom in ("test", "test_perturbe", "test_sms_inedit")
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="éval honnête de la tête")
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
