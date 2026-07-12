#!/usr/bin/env bash
# Entrypoint API Jenny — PRODUCTION (Cloud Run).
#
# Diffère du dev (docker/entrypoint.sh) : pas d'attente TCP de Postgres (Cloud SQL
# se connecte via socket unix / proxy), pas de seed de démo, et migrations OFF par
# défaut (à lancer dans un Cloud Run Job — cf. DEPLOY.md). Écoute sur $PORT (requis
# par Cloud Run, 8080 par défaut).
set -euo pipefail

PORT="${PORT:-8080}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"

# ── Mode démo SANS Redis : 1 worker OBLIGATOIRE ──
# L'état de conversation (slot-filling, RDV en cours) ET le bus d'événements SSE
# du dashboard vivent EN MÉMOIRE quand JENNY_REDIS_URL est vide. Avec plusieurs
# workers uvicorn, chaque process a sa propre mémoire → le contexte du chat saute
# d'un tour à l'autre (tour 1 sur worker A, tour 2 sur worker B). On force donc
# 1 worker tant qu'il n'y a pas de Redis partagé. (Recréer Redis = multi-worker.)
if [ -z "${JENNY_REDIS_URL:-}" ] && [ "${WEB_CONCURRENCY}" != "1" ]; then
  echo "[entrypoint] ⚠️  JENNY_REDIS_URL vide → 1 worker forcé (état + SSE en mémoire)."
  WEB_CONCURRENCY=1
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head…"
  alembic upgrade head
fi

echo "[entrypoint] uvicorn :${PORT} (workers=${WEB_CONCURRENCY})"
exec uvicorn jenny.api.main:app \
  --host 0.0.0.0 --port "${PORT}" \
  --workers "${WEB_CONCURRENCY}" --no-access-log
