# ──────────────────────────────────────────────
# Jenny Worker ARQ — Dockerfile
# ──────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY README.md ./
RUN pip install -e ".[dev]" || pip install .

COPY src/ ./src/
COPY ml/ ./ml/
COPY nanogpt/ ./nanogpt/
COPY pipelines/ ./pipelines/
COPY checkpoints/ ./checkpoints/

CMD ["python", "-m", "arq", "jenny.workers.tasks.WorkerSettings"]
