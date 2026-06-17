"""Mesure RÉELLE de l'accuracy des modèles intention (LSTM) et NER (BiGRU).

Évalue sur un échantillon du jeu de données labellisé et écrit les chiffres dans
var/eval/ml_metrics.json (consommé par le support de présentation).
"""

import json
import random
from pathlib import Path

random.seed(42)
N = 600  # échantillon par modèle


def load_jsonl(path, n):
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    random.shuffle(rows)
    return rows[:n]


def eval_intent():
    from ml.models.intent.predict import IntentPredictor

    p = IntentPredictor.from_checkpoint("checkpoints/intent/best_model.pt")
    rows = load_jsonl("data/generated/intents.jsonl", N)
    ok = 0
    for r in rows:
        true = set(r.get("intents", []))
        res = p.predict_multi(r["text"])
        pred = res.get("primary_intent")
        if pred in true:
            ok += 1
    return {"n": len(rows), "top1_accuracy": round(100 * ok / len(rows), 1)}


def eval_ner():
    from ml.models.ner.predict import NERPredictor

    p = NERPredictor.from_checkpoint("checkpoints/ner/best_model.pt")
    rows = load_jsonl("data/generated/ner.jsonl", N)
    tok_total = tok_ok = 0
    ent_tp = ent_fp = ent_fn = 0
    for r in rows:
        tokens = r.get("tokens", [])
        true_tags = r.get("tags", [])
        if not tokens:
            continue
        pairs = p.predict_with_tags(" ".join(tokens))
        pred_tags = [t for _, t in pairs]
        m = min(len(true_tags), len(pred_tags))
        for i in range(m):
            tok_total += 1
            if true_tags[i] == pred_tags[i]:
                tok_ok += 1
        # F1 entité (ensemble des types présents)
        true_ents = {e["type"] for e in r.get("entities", [])}
        pred_ents = {t.split("-", 1)[1] for t in pred_tags if t != "O" and "-" in t}
        ent_tp += len(true_ents & pred_ents)
        ent_fp += len(pred_ents - true_ents)
        ent_fn += len(true_ents - pred_ents)
    prec = ent_tp / (ent_tp + ent_fp) if (ent_tp + ent_fp) else 0
    rec = ent_tp / (ent_tp + ent_fn) if (ent_tp + ent_fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    return {
        "n": len(rows),
        "token_accuracy": round(100 * tok_ok / tok_total, 1) if tok_total else 0,
        "entity_f1": round(100 * f1, 1),
    }


def main():
    out = {
        "intent_lstm": eval_intent(),
        "ner_bigru": eval_ner(),
    }
    Path("var/eval").mkdir(parents=True, exist_ok=True)
    Path("var/eval/ml_metrics.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
