"""Suivi du modèle maison NanoGPT (entraîné from scratch) + comparaison 3 modèles.

Expose :
- GET /nanogpt/training   → courbe de loss (var/nanogpt/metrics.jsonl) + statut
- GET /nanogpt/comparison → comparaison Groq / Ollama / NanoGPT (var/eval/comparison.json)

Tout est lu sur disque (écrit par `nanogpt.train` et `scripts.compare_models`),
donc la prof voit l'évolution réelle de l'entraînement et la comparaison des perfs.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from jenny.api.dependencies import CurrentUser
from jenny.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/nanogpt", tags=["NanoGPT"])

_METRICS = Path("var/nanogpt/metrics.jsonl")
_STATUS = Path("var/nanogpt/status.json")
_COMPARISON = Path("var/eval/comparison.json")


class TrainingPoint(BaseModel):
    step: int
    train_loss: float
    val_loss: float
    lr: float = 0.0
    tokens_seen: int = 0
    elapsed_s: float = 0.0


class TrainingResponse(BaseModel):
    state: str = "absent"  # absent | running | done
    points: list[TrainingPoint] = []
    step: int = 0
    max_steps: int = 0
    params: int = 0
    vocab_size: int = 0
    best_val_loss: float | None = None
    device: str | None = None
    total_tokens: int | None = None
    model: dict | None = None


@router.get("/training", response_model=TrainingResponse)
async def training(principal: CurrentUser) -> TrainingResponse:
    """Courbe d'entraînement du modèle maison + statut (lecture disque)."""
    points: list[TrainingPoint] = []
    if _METRICS.exists():
        for line in _METRICS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                points.append(TrainingPoint(**json.loads(line)))
            except Exception:
                continue

    status: dict = {}
    if _STATUS.exists():
        try:
            status = json.loads(_STATUS.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("nanogpt.status_read_failed", error=str(exc))

    return TrainingResponse(
        state=status.get("state", "absent" if not points else "done"),
        points=points,
        step=int(status.get("step", points[-1].step if points else 0)),
        max_steps=int(status.get("max_steps", 0)),
        params=int(status.get("params", 0)),
        vocab_size=int(status.get("vocab_size", 0)),
        best_val_loss=status.get("best_val_loss"),
        device=status.get("device"),
        total_tokens=status.get("total_tokens"),
        model=status.get("model"),
    )


class ModelResult(BaseModel):
    key: str
    label: str
    provider: str
    model: str
    available: bool = True
    score_pct: float | None = None
    checks_passed: int | None = None
    checks_total: int | None = None
    avg_latency_ms: float | None = None
    note: str | None = None
    samples: list[dict] | None = None


class ComparisonResponse(BaseModel):
    generated_at: int | None = None
    prompts: int = 0
    results: list[ModelResult] = []


@router.get("/comparison", response_model=ComparisonResponse)
async def comparison(principal: CurrentUser) -> ComparisonResponse:
    """Comparaison Groq / Ollama / NanoGPT (lecture de var/eval/comparison.json)."""
    if not _COMPARISON.exists():
        return ComparisonResponse()
    try:
        data = json.loads(_COMPARISON.read_text(encoding="utf-8"))
        return ComparisonResponse(
            generated_at=data.get("generated_at"),
            prompts=int(data.get("prompts", 0)),
            results=[ModelResult(**r) for r in data.get("results", [])],
        )
    except Exception as exc:
        logger.warning("nanogpt.comparison_read_failed", error=str(exc))
        return ComparisonResponse()
