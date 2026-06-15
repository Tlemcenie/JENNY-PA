#!/bin/sh
# ──────────────────────────────────────────────
# Jenny — Entrypoint API
# Applique les migrations Alembic puis (optionnellement) seed la DB
# avant de lancer la commande passée en argument (uvicorn par défaut).
# ──────────────────────────────────────────────
set -e

echo "[entrypoint] Attente PostgreSQL…"
python - <<'PY'
import asyncio
import os
import socket
import time

host = os.environ.get("JENNY_DB_HOST", "postgres")
port = int(os.environ.get("JENNY_DB_PORT", "5432"))
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] Postgres OK sur {host}:{port}")
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit(f"[entrypoint] Impossible de joindre {host}:{port}")
PY

echo "[entrypoint] Application des migrations Alembic…"
alembic upgrade head || {
    echo "[entrypoint] ⚠ Migration échouée (non bloquant en dev)" >&2
}

if [ "${JENNY_AUTO_SEED:-1}" = "1" ]; then
    echo "[entrypoint] Seed des données de démo…"
    python -m jenny.scripts.seed_demo || \
        echo "[entrypoint] (seed ignoré — aucune fixture disponible)"
fi

echo "[entrypoint] Démarrage : $*"
exec "$@"
