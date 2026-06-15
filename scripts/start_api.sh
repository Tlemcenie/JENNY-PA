#!/bin/bash
# ──────────────────────────────────────────────
# Démarre l'API Jenny en mode développement
# ──────────────────────────────────────────────
set -e

echo "🚀 Démarrage de l'API Jenny..."

# Appliquer les migrations
echo "📦 Application des migrations..."
alembic upgrade head 2>/dev/null || echo "⚠️  Migrations ignorées (DB non disponible)"

# Lancer uvicorn
exec uvicorn jenny.api.main:app \
    --host "${JENNY_API_HOST:-0.0.0.0}" \
    --port "${JENNY_API_PORT:-8000}" \
    --reload
