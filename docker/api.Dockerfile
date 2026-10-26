# ──────────────────────────────────────────────
# Jenny API — Dockerfile (dev, docker compose)
# Prod : docker/api.prod.Dockerfile
# ──────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl && \
    rm -rf /var/lib/apt/lists/*

# torch CPU : pas de CUDA
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3.0"

# src avant l'install éditable
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/
RUN pip install -e ".[dev]"

# mpnet en cache dans l'image
ARG EMBED_MODEL=paraphrase-multilingual-mpnet-base-v2
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBED_MODEL}', device='cpu')"

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
