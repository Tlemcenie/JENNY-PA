"""entraîne la tête d'intention.

Usage : PYTHONPATH=src:. .venv/bin/python -m ml.models.intent_head.train
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from itertools import pairwise
from pathlib import Path

import joblib
import numpy as np

from ml.models.intent.config import INTENT_LABELS, LABEL_TO_ID
from ml.models.intent_head.augment import perturb_eval, variants
from ml.models.intent_head.data import (
    DATA_PATH,
    Group,
    frozen_split,
    group_train,
    labels_of,
    load_rows,
)
from ml.models.intent_head.features import CharNgrams
from ml.models.intent_head.predict import ENCODER_NAME, FORMAT, encode, get_encoder, softmax

OUT = Path("checkpoints/intent_head/head.joblib")
CONFLICTS_OUT = Path("data/generated/intents_head_conflicts.json")
GRID_C = (2.0, 4.0, 8.0, 16.0, 32.0)
# poids du bloc n-grammes (0 = mpnet seul)
GRID_ALPHA = (0.0, 0.5, 1.0)
MAX_INTENTS = 3
CLARIFY_THRESHOLD = 0.5
MIN_DF = 2


class EmbedCache:
    """embeddings calculés une fois."""

    def __init__(self, encoder: object) -> None:
        self.encoder = encoder
        self.vecs: dict[str, np.ndarray] = {}

    def __call__(self, texts: list[str]) -> np.ndarray:
        todo = sorted({t for t in texts if t not in self.vecs})
        if todo:
            for t, v in zip(todo, encode(self.encoder, todo), strict=True):
                self.vecs[t] = v
        return np.stack([self.vecs[t] for t in texts])


def resolve_conflicts(groups: list[Group], embed: EmbedCache) -> list[dict]:
    """vote majoritaire, sinon centroïde."""
    clean = [g for g in groups if not g.conflict]
    for g in clean:
        g.label = next(iter(g.votes))
    # centroïdes du train propre
    vecs = embed([g.text for g in clean])
    centroids = {}
    for lab in INTENT_LABELS:
        rows = [v for g, v in zip(clean, vecs, strict=True) if g.label == lab]
        if rows:
            c = np.mean(rows, axis=0)
            centroids[lab] = c / (np.linalg.norm(c) + 1e-9)

    report = []
    for g in groups:
        if not g.conflict:
            continue
        tied = g.tied()
        if len(tied) == 1:
            g.label, rule = tied[0], "majorite"
        else:
            v = embed([g.text])[0]
            g.label = max(tied, key=lambda lab: float(v @ centroids.get(lab, np.zeros_like(v))))
            rule = "centroide"
        report.append({"text": g.text, "votes": dict(g.votes), "label": g.label, "regle": rule})
    return report


def build_train(groups: list[Group]) -> tuple[list[str], list[str]]:
    """train augmenté."""
    texts: list[str] = []
    labels: list[str] = []
    for g in groups:
        for v in variants(g.text):
            texts.append(v)
            labels.append(g.label)
    return texts, labels


def features(emb: np.ndarray, chars: CharNgrams | None, texts: list[str], alpha: float) -> object:
    """mpnet + n-grammes pondérés."""
    if chars is None or alpha <= 0:
        return emb
    from scipy.sparse import csr_matrix, hstack

    return hstack([csr_matrix(emb), alpha * chars.transform(texts)]).tocsr()


def fit_head(x: object, y: list[str], c: float) -> tuple[np.ndarray, np.ndarray]:
    """régression logistique multinomiale."""
    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(C=c, class_weight="balanced", max_iter=5000, solver="lbfgs")
    clf.fit(x, y)
    classes = list(clf.classes_)
    missing = [lab for lab in INTENT_LABELS if lab not in classes]
    if missing:
        raise ValueError(f"classes absentes du train : {missing}")
    order = [classes.index(lab) for lab in INTENT_LABELS]
    coef = clf.coef_[order].astype(np.float32)
    intercept = clf.intercept_[order].astype(np.float32)
    # vérifie le softmax maison
    head = x[:50]
    dense = head.toarray() if hasattr(head, "toarray") else head
    ref = clf.predict_proba(head)[:, order]
    if not np.allclose(ref, softmax(dense @ coef.T + intercept), atol=1e-4):
        raise RuntimeError("probas différentes de sklearn")
    return coef, intercept


def logits_of(x: object, coef: np.ndarray, b: np.ndarray) -> np.ndarray:
    """logits bruts."""
    return np.asarray(x @ coef.T) + b


def top1(probs: np.ndarray, gold: np.ndarray) -> float:
    """précision top-1 en %."""
    return float(100 * np.mean(probs.argmax(axis=1) == gold))


def fit_temperature(logits: np.ndarray, gold: np.ndarray) -> float:
    """température par nll sur val."""
    best_t, best_nll = 1.0, float("inf")
    for t in np.exp(np.linspace(np.log(0.05), np.log(10.0), 600)):
        p = softmax(logits / t)
        nll = float(-np.mean(np.log(p[np.arange(len(gold)), gold] + 1e-12)))
        if nll < best_nll:
            best_t, best_nll = float(t), nll
    return best_t


def ece(probs: np.ndarray, gold: np.ndarray, bins: int = 15) -> float:
    """erreur de calibration en %."""
    conf = probs.max(axis=1)
    ok = probs.argmax(axis=1) == gold
    total = 0.0
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in pairwise(edges):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(ok[m].mean() - conf[m].mean())
    return round(100 * float(total), 2)


def label_sets(probs: np.ndarray, t: float) -> list[set[int]]:
    """top-1 + secondaires au-dessus de t."""
    out = []
    for p in probs:
        order = np.argsort(-p, kind="stable")
        s = {int(order[0])}
        for j in order[1:MAX_INTENTS]:
            if p[int(j)] < t:
                break
            s.add(int(j))
        out.append(s)
    return out


def set_f1(pred: list[set[int]], gold: list[set[int]]) -> float:
    """f1 par exemple en %."""
    tot = 0.0
    for p, g in zip(pred, gold, strict=True):
        tot += 2 * len(p & g) / (len(p) + len(g))
    return float(100 * tot / len(gold))


def fit_multi_threshold(probs: np.ndarray, gold_sets: list[set[int]]) -> tuple[float, float]:
    """seuil multi-intention sur val."""
    scores = []
    for t in np.round(np.arange(0.10, 0.71, 0.01), 2):
        scores.append((float(t), set_f1(label_sets(probs, float(t)), gold_sets)))
    best = max(f1 for _, f1 in scores)
    # à 0,5 pt près : le plus prudent
    t = max(t for t, f1 in scores if f1 >= best - 0.5)
    return t, round(dict(scores)[t], 2)


def train(data_path: Path = DATA_PATH, out: Path = OUT) -> dict:
    """pipeline complet, val seule."""
    import sklearn

    t0 = time.time()
    rows = load_rows(data_path)
    split = frozen_split(len(rows))
    embed = EmbedCache(get_encoder(ENCODER_NAME))

    # 1. train propre et augmenté
    groups = group_train(rows, split["train"])
    report = resolve_conflicts(groups, embed)
    texts, labels = build_train(groups)
    x_emb = embed(texts)
    chars = CharNgrams().fit(texts, min_df=MIN_DF)

    # 2. val propre et perturbée
    val_rows = [rows[i] for i in split["val"]]
    val_gold = np.array([LABEL_TO_ID[labels_of(r)[0]] for r in val_rows])
    val_sets = [{LABEL_TO_ID[lab] for lab in labels_of(r)} for r in val_rows]
    val_txt = [r["text"] for r in val_rows]
    val_txt_p = [perturb_eval(t) for t in val_txt]
    e_val, e_val_p = embed(val_txt), embed(val_txt_p)

    # 3. grille alpha x C
    grid = []
    best: dict | None = None
    for alpha in GRID_ALPHA:
        x = features(x_emb, chars, texts, alpha)
        xv = features(e_val, chars, val_txt, alpha)
        xvp = features(e_val_p, chars, val_txt_p, alpha)
        for c in GRID_C:
            coef, b = fit_head(x, labels, c)
            acc = top1(softmax(logits_of(xv, coef, b)), val_gold)
            acc_p = top1(softmax(logits_of(xvp, coef, b)), val_gold)
            score = (acc + acc_p) / 2
            grid.append(
                {"alpha": alpha, "C": c, "val_top1": round(acc, 2), "val_perturbe": round(acc_p, 2)}
            )
            print(f"  alpha={alpha} C={c:<5} val={acc:.2f}  val_perturbe={acc_p:.2f}", flush=True)
            if best is None or score > best["score"] + 1e-9:
                best = {"score": score, "alpha": alpha, "C": c, "coef": coef, "b": b}
    assert best is not None

    # 4. calibration sur val
    alpha, coef, b = best["alpha"], best["coef"], best["b"]
    dim = x_emb.shape[1]
    coef_emb = coef[:, :dim]
    # alpha replié dans les poids
    coef_char = alpha * coef[:, dim:] if alpha > 0 else None
    xv = features(e_val, chars, val_txt, alpha)
    xvp = features(e_val_p, chars, val_txt_p, alpha)
    logits = np.concatenate([logits_of(xv, coef, b), logits_of(xvp, coef, b)])
    gold2 = np.concatenate([val_gold, val_gold])
    temp = fit_temperature(logits, gold2)
    probs_val = softmax(logits_of(xv, coef, b) / temp)
    probs_val_p = softmax(logits_of(xvp, coef, b) / temp)
    multi_t, multi_f1 = fit_multi_threshold(probs_val, val_sets)
    single = [i for i, s in enumerate(val_sets) if len(s) == 1]
    sets_single = label_sets(probs_val[single], multi_t)
    conf = probs_val.max(axis=1)
    ok = probs_val.argmax(axis=1) == val_gold
    low = conf < CLARIFY_THRESHOLD

    meta = {
        "encoder": ENCODER_NAME,
        "data": str(data_path),
        "data_sha256": hashlib.sha256(Path(data_path).read_bytes()).hexdigest(),
        "split": {k: len(v) for k, v in split.items()},
        "train_lignes": len(split["train"]),
        "train_textes_uniques": len(groups),
        "doublons_retires": len(split["train"]) - len(groups),
        "conflits_train": len(report),
        "conflits_majorite": sum(r["regle"] == "majorite" for r in report),
        "conflits_centroide": sum(r["regle"] == "centroide" for r in report),
        "train_augmente": len(texts),
        "char_vocab": len(chars) if coef_char is not None else 0,
        "alpha": alpha,
        "C": best["C"],
        "grille": grid,
        "temperature": round(temp, 4),
        "ece_val_avant": ece(softmax(logits), gold2),
        "ece_val_apres": ece(softmax(logits / temp), gold2),
        "multi_threshold": multi_t,
        "val_multi_f1": multi_f1,
        "val_faux_multi_pct": round(100 * np.mean([len(s) > 1 for s in sets_single]), 2),
        "val_top1": round(top1(probs_val, val_gold), 2),
        "val_perturbe_top1": round(top1(probs_val_p, val_gold), 2),
        "val_clarif_pct": round(100 * float(low.mean()), 2),
        "val_precision_sous_seuil": round(100 * float(ok[low].mean()), 2) if low.any() else None,
        "val_precision_au_dessus": round(100 * float(ok[~low].mean()), 2),
        "sklearn": sklearn.__version__,
        "duree_s": round(time.time() - t0, 1),
    }
    ckpt = {
        "format": FORMAT,
        "encoder": ENCODER_NAME,
        "normalize": True,
        "labels": list(INTENT_LABELS),
        "coef": coef_emb,
        "intercept": b,
        "char_coef": coef_char,
        "char_vocab": chars.vocab if coef_char is not None else None,
        "char_idf": chars.idf if coef_char is not None else None,
        "char_ngram": [chars.n_min, chars.n_max],
        "temperature": temp,
        "multi_threshold": multi_t,
        "max_intents": MAX_INTENTS,
        "clarify_threshold": CLARIFY_THRESHOLD,
        "meta": meta,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(ckpt, out, compress=3)
    (out.parent / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    CONFLICTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONFLICTS_OUT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


def main() -> None:
    """point d'entrée cli."""
    parser = argparse.ArgumentParser(description="tête d'intention mpnet")
    parser.add_argument("--data", default=str(DATA_PATH))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    meta = train(Path(args.data), Path(args.out))
    resume = {k: v for k, v in meta.items() if k != "grille"}
    print(json.dumps(resume, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
