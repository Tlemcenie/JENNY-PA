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

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head…"
  alembic upgrade head
fi

echo "[entrypoint] uvicorn :${PORT} (workers=${WEB_CONCURRENCY})"
exec uvicorn jenny.api.main:app \
  --host 0.0.0.0 --port "${PORT}" \
  --workers "${WEB_CONCURRENCY}" --no-access-log
