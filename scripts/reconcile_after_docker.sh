#!/usr/bin/env bash
# Réconciliation après redémarrage de Docker Desktop.
# Applique les migrations en attente (is_superuser + appointments), crée le
# compte super-admin, puis relance API + worker. À lancer depuis la racine du
# repo une fois Docker Desktop redémarré.
#
#   bash scripts/reconcile_after_docker.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ 1/5 Démarrage Postgres + Redis…"
docker compose up -d postgres redis

echo "▶ 2/5 Attente que Postgres réponde…"
for i in $(seq 1 30); do
  if docker exec jenny-postgres pg_isready -U jenny >/dev/null 2>&1; then
    echo "   Postgres prêt."
    break
  fi
  sleep 2
done

echo "▶ 3/5 Application des migrations (alembic upgrade head)…"
source .venv/bin/activate
alembic upgrade head

echo "▶ 4/5 Création / promotion du super-admin…"
PYTHONPATH=src python -m jenny.scripts.create_admin

echo "▶ 5/5 Redémarrage API + worker…"
pkill -f "uvicorn jenny.api.main" 2>/dev/null || true
pkill -f "arq jenny.workers.tasks" 2>/dev/null || true
sleep 2
mkdir -p var
PYTHONPATH=src nohup python -m uvicorn jenny.api.main:app --host 0.0.0.0 --port 8000 > var/api.log 2>&1 &
PYTHONPATH=src nohup python -m arq jenny.workers.tasks.WorkerSettings > var/worker.log 2>&1 &
sleep 6
code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health || echo 000)
echo "   API /health → $code"
echo "✅ Réconciliation terminée. Admin : admin@jenny.ai / Admin!2026"
