"""Script d'entraînement NanoGPT.

Boucle d'entraînement complète avec :
- Chargement des données
- Optimiseur AdamW
- Learning rate schedule (cosine avec warmup)
- Logging MLflow
- Sauvegarde de checkpoints
"""

from pathlib import Path

import torch
from torch.optim import AdamW

from jenny.core.logging import get_logger
from nanogpt.config import NanoGPTConfig
from nanogpt.model import NanoGPT

logger = get_logger(__name__)


def get_lr(step: int, config: NanoGPTConfig, max_steps: int) -> float:
    """Calcule le learning rate avec warmup linéaire + cosine decay."""
    import math

    if step < config.warmup_steps:
        return config.learning_rate * step / config.warmup_steps

    decay_ratio = (step - config.warmup_steps) / max(max_steps - config.warmup_steps, 1)
    coeff = 0.5 * (1.0 + math.cos(math.pi * decay_ratio))
    return config.learning_rate * max(coeff, 0.1)


def train_nanogpt(
    config: NanoGPTConfig | None = None,
    data_path: str | None = None,
) -> NanoGPT:
    """Entraîne un modèle NanoGPT.

    Args:
        config: Configuration (défaut si None).
        data_path: Chemin vers les données tokenizées.

    Returns:
        Modèle entraîné.

    TODO: implémenter le chargement des données réelles.
    """
    config = config or NanoGPTConfig()
    torch.manual_seed(config.seed)

    logger.info(
        "nanogpt.train.start",
        n_layer=config.n_layer,
        n_head=config.n_head,
        n_embd=config.n_embd,
        vocab_size=config.vocab_size,
    )

    # Modèle
    model = NanoGPT(config)
    model = model.to(config.device)
    logger.info("nanogpt.params", count=f"{model.count_parameters():,}")

    if config.compile_model:
        model = torch.compile(model)  # type: ignore[assignment]

    # Optimiseur
    AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    # ── Boucle d'entraînement (placeholder) ──
    # TODO: remplacer par un vrai DataLoader
    logger.info(
        "nanogpt.train.placeholder",
        message="Pas de données chargées — la boucle sera implémentée en Phase 6",
    )

    # Sauvegarde du modèle initial
    checkpoint_dir = Path("checkpoints/nanogpt")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"model_state_dict": model.state_dict(), "config": config},
        checkpoint_dir / "initial.pt",
    )
    logger.info("nanogpt.train.saved", path=str(checkpoint_dir / "initial.pt"))

    return model


if __name__ == "__main__":
    train_nanogpt()
