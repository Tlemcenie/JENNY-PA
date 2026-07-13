# syntax=docker/dockerfile:1
# ── Image API Jenny — PRODUCTION (Cloud Run) ──
# Optimisée vs docker/api.Dockerfile (dev) :
#  - PyTorch CPU (index officiel) → ~200 Mo au lieu du wheel CUDA (~2,5 Go) ;
#  - dépendances de PROD uniquement (pas de .[dev]) ;
#  - venv multi-stage → image runtime mince, utilisateur non-root ;
#  - écoute sur $PORT (Cloud Run), migrations en option (Job recommandé).
#
# mlflow/datasets restent installés (deps cœur) mais ne sont PAS importés par le
# chemin de service (jenny.api/engine) ; le gros gain vient du torch CPU.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

# 1) Torch CPU AVANT le reste → satisfait la contrainte, évite le wheel CUDA.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3.0"

# 2) Dépendances de prod (le paquet jenny + ses deps ; torch déjà présent).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# ── Runtime ──
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" PYTHONPATH="/app/src:/app" \
    PORT=8080 JENNY_ENABLE_ML_MODELS=true RUN_MIGRATIONS=0

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY ml ./ml
COPY nanogpt ./nanogpt
COPY migrations ./migrations
COPY alembic.ini ./
COPY checkpoints ./checkpoints
COPY docker/entrypoint.prod.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R app:app /app

USER app
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
