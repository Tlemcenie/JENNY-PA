# NanoGPT « maison » — runbook gros run (Tesla T4)

Modèle de langue **entraîné de zéro** (aucun fine-tune, poids initialisés au hasard)
sur un gros corpus FR, pour comparer avec Groq et Ollama. Tout est réel et reprenable.

## TL;DR — ce soir, sur la machine T4

```bash
# 1. Récupérer le repo sur la machine T4, créer l'env
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu121   # build CUDA
pip install datasets tokenizers numpy matplotlib

# 2. (recommandé) login HF — débloque OSCAR/CulturaX + enlève les limites de débit
huggingface-cli login        # ou : export HF_TOKEN=hf_xxx

# 3. Lancer (collecte ~2 Go + entraînement 40k steps, AMP, ~1–3 h sur T4)
bash scripts/train_t4.sh
#   réglable :  TARGET_MB=3000 MAX_STEPS=60000 bash scripts/train_t4.sh
#   reprise  :  RESUME=1 bash scripts/train_t4.sh
```

## Ce que ça fait

1. **Collecte** (`nanogpt/data.py`) — corpus FR cumulé jusqu'à `TARGET_MB` :
   - **Datasets HF** (streaming) : FineWeb-2 FR, Wikipédia FR, C4 FR, + *(gated)* CulturaX, OSCAR → langue générale.
   - **Q&R / FAQ FR** : PIAF, newsquadfr → saveur « questions client ».
   - **Scraping** : ~24 pages Wikipédia FR ciblées (coiffure, beauté, relation/service client, RDV, paiement…).
   - **Interne Jenny** : scénarios d'éval + intents.
   - → tokenizer **BPE entraîné de zéro** (`checkpoints/nanogpt/tokenizer.json`) + `data/processed/{train,val}.bin`.
   - **Internet n'est nécessaire QUE pour cette étape.** L'entraînement ensuite est 100 % local.
2. **Entraînement** (`nanogpt/train.py`) — GPT decoder-only from scratch :
   - device auto **CUDA** (T4) > MPS > CPU ; **mixed precision fp16** (`--amp`) + **accumulation de gradient** (`--grad-accum`).
   - LR warmup + cosine, éval val périodique, **courbe → `var/nanogpt/metrics.jsonl`**, checkpoints `best`/`last`, **reprenable** (`--resume`).
   - Defaults T4 : `n_layer 8 · n_embd 512 · block 512 · vocab 32k` (~45 M params), batch 32 × grad-accum 4 (= 128 effectif).

## Suivi

- **Live** : page `/lab` « Modèle maison » dans l'app (courbe qui se rafraîchit) si l'API tourne.
- **Terminal** : `tail -f var/nanogpt/metrics.jsonl`
- **PNG (pour la prof)** : `python scripts/plot_training.py` → `var/nanogpt/training_curve.png`

## Après l'entraînement

```bash
python scripts/compare_models.py   # rejoue la comparaison Groq / Ollama / NanoGPT
```
→ met à jour `var/eval/comparison.json` (lu par `/lab` + l'onglet Efficacité).

## Notes honnêtes

- Un from-scratch ~45 M params sur ~2 Go reste **bien plus faible** que Groq-70B / Ollama-7B :
  l'intérêt est la **démarche** (data → entraînement de zéro → courbes → comparaison), pas de gagner.
- **OOM** sur la T4 → baisser `--batch-size` (16/8), monter `--grad-accum` (8/16) : le batch effectif reste constant.
- Plus de données / steps = courbe plus basse. C'est borné par le temps GPU, pas par la donnée disponible.
