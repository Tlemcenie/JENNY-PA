# ──────────────────────────────────────────────
# Jenny API — Dockerfile
# ──────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/
RUN pip install -e ".[dev]" || pip install .

COPY ml/ ./ml/
COPY nanogpt/ ./nanogpt/
COPY pipelines/ ./pipelines/
COPY checkpoints/ ./checkpoints/
COPY scripts/ ./scripts/
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "jenny.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
