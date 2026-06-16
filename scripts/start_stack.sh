#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────
# Démarre TOUT le stack local de Jenny d'un coup (idempotent) :
#   Postgres (5433) · Redis (6381) · [vérifie Ollama 11434] · API (8000)
#
# À lancer quand « rien ne marche » : en général c'est Postgres/Redis qui se
# sont arrêtés (Mac en veille / redémarrage). Le front se lance à part :
#   cd frontend && npm run dev
#
# Usage :  bash scripts/start_stack.sh
# ──────────────────────────────────────────────────────────────────────────
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PGDATA="$ROOT/var/pgdata"
PGBIN="/opt/homebrew/opt/postgresql@17/bin"
PY="$ROOT/.venv/bin/python"

port_open() { "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1)
sys.exit(0) if s.connect_ex(('localhost',$1))==0 else sys.exit(1)" 2>/dev/null; }

# ── 1. Postgres ──
if port_open 5433; then
  echo "✅ Postgres déjà up (5433)"
else
  echo "🐘 Démarrage de Postgres (5433)…"
  # postmaster.pid périmé après un arrêt brutal → on le retire pour pouvoir relancer.
  [ -f "$PGDATA/postmaster.pid" ] && rm -f "$PGDATA/postmaster.pid"
  LC_ALL=en_US.UTF-8 "$PGBIN/pg_ctl" -D "$PGDATA" -l "$ROOT/var/pg.log" -o "-p 5433" -w -t 30 start \
    && echo "   → Postgres OK" || echo "   ⚠️  Échec Postgres (voir var/pg.log)"
fi

# ── 2. Redis ──
if port_open 6381; then
  echo "✅ Redis déjà up (6381)"
else
  echo "🧱 Démarrage de Redis (6381)…"
  REDIS_BIN="$(command -v redis-server || echo /opt/homebrew/bin/redis-server)"
  "$REDIS_BIN" --port 6381 --daemonize yes && echo "   → Redis OK" || echo "   ⚠️  redis-server introuvable (brew install redis)"
fi

# ── 3. Ollama (utilisé par le RAG + l'option LLM locale) ──
if port_open 11434; then
  echo "✅ Ollama déjà up (11434)"
elif command -v ollama >/dev/null; then
  echo "🦙 Démarrage d'Ollama (11434)…"
  nohup ollama serve >> "$ROOT/var/ollama.log" 2>&1 &
  disown
  for _ in $(seq 1 15); do port_open 11434 && break; sleep 1; done
  port_open 11434 && echo "   → Ollama OK" || echo "   ⚠️  Ollama lent à démarrer (voir var/ollama.log)"
else
  echo "⚠️  ollama introuvable — RAG et modèle local indisponibles (Groq fonctionne sans)."
fi

# ── 4. API ──
echo "🚀 (Re)démarrage de l'API (8000)…"
pkill -f "uvicorn jenny.api.main" 2>/dev/null && sleep 1
export JENNY_DATABASE_URL="postgresql+asyncpg://jenny:jenny@localhost:5433/jenny"
export JENNY_REDIS_URL="redis://localhost:6381/0"
nohup "$PY" -m uvicorn jenny.api.main:app --host 127.0.0.1 --port 8000 \
  >> "$ROOT/var/api_8000.log" 2>&1 &
disown
# Attente que /health réponde.
for _ in $(seq 1 30); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://127.0.0.1:8000/health 2>/dev/null)" = "200" ]; then
    echo "   → API OK (http://127.0.0.1:8000)"; break
  fi; sleep 1
done

echo ""
echo "✨ Stack prêt. Front : cd frontend && npm run dev  (→ http://localhost:3000)"
echo "   Connexion démo : demo@jenny.ai / Demo!1234"
