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

# Données lab : écrites dans var/ par l'entraînement/éval (dev), MAIS var/ n'est pas
# embarqué dans l'image de prod. On lit donc var/ en priorité (live/dev), sinon le
# snapshot embarqué dans le paquet (src/jenny/assets/lab) → l'onglet marche partout,
# quel que soit le répertoire de lancement (chemins absolus, pas relatifs au CWD).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BUNDLED = Path(__file__).resolve().parents[2] / "assets" / "lab"


def _lab_path(rel_var: str, bundled_name: str) -> Path:
    live = _REPO_ROOT / rel_var
    return live if live.exists() else _BUNDLED / bundled_name


_METRICS = _lab_path("var/nanogpt/metrics.jsonl", "metrics.jsonl")
_STATUS = _lab_path("var/nanogpt/status.json", "status.json")
_COMPARISON = _lab_path("var/eval/comparison.json", "comparison.json")


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
