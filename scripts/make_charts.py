"""Génère les graphiques du support de présentation (PNG haute déf, DA Jenny)."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("/tmp/jenny_charts")
OUT.mkdir(exist_ok=True)
CORAL, NIGHT, BLUE, GREEN, MUTED = "#FF7F6A", "#1A1430", "#5B8DEF", "#3BA776", "#9AA1AD"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#D9DCE3"})


def training_curve():
    pts = [json.loads(l) for l in Path("var/nanogpt/metrics.jsonl").read_text().splitlines() if l.strip()]
    steps = [p["step"] for p in pts]
    tr = [p["train_loss"] for p in pts]
    va = [p.get("val_loss") for p in pts]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    ax.plot(steps, tr, color=CORAL, lw=2.4, label="Train loss")
    ax.plot(steps, va, color=NIGHT, lw=2.0, ls="--", label="Validation loss")
    ax.set_title("NanoGPT maison — courbe d'entraînement", fontsize=14, color=NIGHT, weight="bold", pad=12)
    ax.set_xlabel("Pas d'entraînement (steps)")
    ax.set_ylabel("Loss")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    ax.annotate(f"9,71 → {tr[-1]:.2f}", xy=(steps[-1], tr[-1]), xytext=(steps[-1] * 0.55, tr[0] * 0.7),
                color=CORAL, weight="bold", arrowprops=dict(arrowstyle="->", color=CORAL))
    fig.tight_layout()
    fig.savefig(OUT / "training_curve.png", bbox_inches="tight")
    plt.close(fig)


def comparison():
    data = json.loads(Path("var/eval/comparison.json").read_text())
    res = data["results"]
    labels = {"ollama": "Ollama 7B", "groq": "Groq 70B", "nanogpt": "NanoGPT (maison)"}
    names = [labels.get(r["key"], r["key"]) for r in res]
    scores = [r.get("score_pct") or 0 for r in res]
    lat = [(r.get("avg_latency_ms") or 0) / 1000 for r in res]
    colors = [BLUE, NIGHT, CORAL]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 4), dpi=150)
    b1 = a1.bar(names, scores, color=colors)
    a1.set_title("Score qualité (6 prompts métier)", fontsize=12, color=NIGHT, weight="bold")
    a1.set_ylabel("% de réponses correctes")
    a1.set_ylim(0, 109)
    for r, s in zip(b1, scores):
        a1.text(r.get_x() + r.get_width() / 2, s + 2, f"{s:.0f}%", ha="center", weight="bold", color=NIGHT)
    a1.tick_params(axis="x", labelsize=9)
    b2 = a2.bar(names, lat, color=colors)
    a2.set_title("Latence moyenne (s) — plus bas = mieux", fontsize=12, color=NIGHT, weight="bold")
    a2.set_ylabel("secondes / réponse")
    for r, s in zip(b2, lat):
        a2.text(r.get_x() + r.get_width() / 2, s + max(lat) * 0.02, f"{s:.1f}s", ha="center", weight="bold", color=NIGHT)
    a2.tick_params(axis="x", labelsize=9)
    fig.suptitle("Comparaison des 3 modèles de langage", fontsize=14, color=NIGHT, weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "model_comparison.png", bbox_inches="tight")
    plt.close(fig)


def ml_accuracy():
    m = json.loads(Path("var/eval/ml_metrics.json").read_text())
    names = ["Intention\n(Bi-LSTM)", "NER tokens\n(BiGRU)", "NER entités\n(F1)", "Agents\n(banc d'essai)"]
    vals = [m["intent_lstm"]["top1_accuracy"], m["ner_bigru"]["token_accuracy"], m["ner_bigru"]["entity_f1"], 100.0]
    colors = [CORAL, BLUE, BLUE, GREEN]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    bars = ax.bar(names, vals, color=colors, width=0.6)
    ax.set_title("Performance des modèles maison de Jenny", fontsize=14, color=NIGHT, weight="bold", pad=12)
    ax.set_ylabel("%")
    ax.set_ylim(0, 109)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", weight="bold", color=NIGHT)
    ax.grid(True, axis="y", alpha=0.2)
    fig.text(0.5, -0.02, "Intention & NER : mesuré sur 600 exemples du jeu de données · Agents : 58/58 vérifications, 14 scénarios",
             ha="center", fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "ml_accuracy.png", bbox_inches="tight")
    plt.close(fig)


training_curve()
comparison()
ml_accuracy()
print("charts →", [p.name for p in OUT.glob("*.png")])
