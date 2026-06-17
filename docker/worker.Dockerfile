# syntax=docker/dockerfile:1
# ── Image Worker Jenny (ARQ cron : rappels, avis, relances) — PRODUCTION ──
# Miroir de docker/api.prod.Dockerfile : torch CPU, deps de prod, multi-stage,
# non-root. Le worker importe le moteur ML (intent predictor) → torch + ml +
# checkpoints (intent/ner ; nanogpt exclu via .dockerignore) sont nécessaires.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

# 1) Torch CPU AVANT le reste (évite le wheel CUDA).
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3.0"

# 2) Le paquet jenny + deps de prod. src/ DOIT être présent (layout src/).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# ── Runtime ──
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" PYTHONPATH="/app/src:/app" \
    JENNY_ENABLE_ML_MODELS=true

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY ml ./ml
COPY migrations ./migrations
COPY alembic.ini ./
COPY checkpoints ./checkpoints
RUN chown -R app:app /app

USER app
CMD ["python", "-m", "arq", "jenny.workers.tasks.WorkerSettings"]
