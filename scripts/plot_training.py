"""Exporte la courbe d'entraînement NanoGPT en PNG (pour le rapport / la prof).

Lit var/nanogpt/metrics.jsonl → var/nanogpt/training_curve.png

Usage : .venv/bin/python scripts/plot_training.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "var" / "nanogpt" / "metrics.jsonl"
OUT = ROOT / "var" / "nanogpt" / "training_curve.png"


def main() -> int:
    if not METRICS.exists():
        print(f"Pas de métriques ({METRICS}). Lance d'abord `python -m nanogpt.train`.")
        return 1
    rows = [json.loads(line) for line in METRICS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        print("Aucun point de métrique.")
        return 1

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"matplotlib indisponible ({exc}). `pip install matplotlib` pour le PNG.")
        return 1

    steps = [r["step"] for r in rows]
    train = [r["train_loss"] for r in rows]
    val = [r["val_loss"] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=120)
    ax.plot(steps, train, color="#FF7F6A", linewidth=2.2, label="train loss")
    ax.plot(steps, val, color="#7284A8", linewidth=2.2, label="val loss")
    ax.set_title("NanoGPT — entraînement from scratch (loss)", fontsize=14, fontweight="bold")
    ax.set_xlabel("étape (step)")
    ax.set_ylabel("cross-entropy loss")
    ax.grid(True, alpha=0.18)
    ax.legend(frameon=False)
    best = min(val)
    ax.annotate(
        f"meilleure val loss : {best:.3f}",
        xy=(steps[val.index(best)], best),
        xytext=(0.55, 0.85), textcoords="axes fraction",
        fontsize=10, color="#7284A8",
    )
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT)
    print(f"✓ courbe écrite : {OUT}  ({len(rows)} points, val finale {val[-1]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
