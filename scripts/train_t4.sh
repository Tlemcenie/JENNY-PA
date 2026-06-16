#!/usr/bin/env bash
# ── Gros run NanoGPT from scratch sur GPU (idéal Tesla T4 16 Go) ──
# Collecte un GROS corpus FR (datasets + scraping) puis entraîne DE ZÉRO
# (aucun fine-tune) avec mixed-precision + accumulation de gradient.
#
# Usage simple :   bash scripts/train_t4.sh
# Réglable :        TARGET_MB=3000 MAX_STEPS=60000 bash scripts/train_t4.sh
# Reprise :         RESUME=1 bash scripts/train_t4.sh      (reprend l'entraînement)
#
# Pré-requis sur la machine T4 :
#   - PyTorch build CUDA installé (torch.cuda.is_available() == True)
#   - pip install "datasets" "tokenizers" "numpy"
#   - (recommandé) huggingface-cli login   → débloque OSCAR/CulturaX + enlève les
#     limites de débit. Sinon ces sources gated sont ignorées automatiquement.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
command -v "$PY" >/dev/null 2>&1 || PY="python3"

TARGET_MB="${TARGET_MB:-2000}"     # ~2 Go de texte FR ≈ ~500 M tokens
VOCAB="${VOCAB:-32000}"
MAX_STEPS="${MAX_STEPS:-40000}"
RESUME_FLAG=""
[ "${RESUME:-0}" = "1" ] && RESUME_FLAG="--resume"

echo "════════════════════════════════════════════════════════════════"
echo " NanoGPT from scratch — gros run GPU"
echo "  corpus≈${TARGET_MB} Mo · vocab ${VOCAB} · steps ${MAX_STEPS}"
echo "════════════════════════════════════════════════════════════════"
"$PY" - <<'PYEOF'
import torch
print(f"[env] torch {torch.__version__} | cuda dispo: {torch.cuda.is_available()}"
      + (f" | GPU: {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else " (⚠ CPU — vérifie le build CUDA)"))
PYEOF

if [ -z "$RESUME_FLAG" ]; then
  echo "── 1/2 · Collecte corpus + tokenizer BPE (internet requis ici uniquement) ──"
  "$PY" -m nanogpt.data --target-mb "$TARGET_MB" --vocab-size "$VOCAB"
else
  echo "── (reprise) on garde le corpus/tokenizer existants ──"
fi

echo "── 2/2 · Entraînement from scratch (AMP fp16 + grad-accum) ──"
"$PY" -m nanogpt.train \
  --max-steps "$MAX_STEPS" --eval-interval 500 --eval-iters 100 \
  --n-layer 8 --n-head 8 --n-embd 512 --block-size 512 \
  --batch-size 32 --grad-accum 4 --amp \
  --warmup 800 --lr 6e-4 $RESUME_FLAG

echo ""
echo "✓ Terminé."
echo "  Courbe   : var/nanogpt/metrics.jsonl  →  $PY scripts/plot_training.py  (PNG)"
echo "  Modèle   : checkpoints/nanogpt/best_model.pt (+ tokenizer.json)"
echo "  Comparer : $PY scripts/compare_models.py"
echo ""
echo "  Si OOM sur la T4 : baisse --batch-size (16/8) et monte --grad-accum (8/16)."
