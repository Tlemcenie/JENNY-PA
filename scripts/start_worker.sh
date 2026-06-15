#!/bin/bash
# ──────────────────────────────────────────────
# Démarre le worker ARQ Jenny
# ──────────────────────────────────────────────
set -e

echo "⚙️  Démarrage du worker ARQ Jenny..."

exec python -m arq jenny.workers.tasks.WorkerSettings
