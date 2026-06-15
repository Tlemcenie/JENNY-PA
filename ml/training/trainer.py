"""Trainer générique pour les modèles ML Jenny.

Fournit une base pour entraîner des modèles PyTorch
avec logging MLflow intégré.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TrainingConfig:
    """Configuration d'un run d'entraînement."""

    experiment_name: str = "jenny-default"
    epochs: int = 10
    learning_rate: float = 1e-4
    batch_size: int = 32
    checkpoint_dir: str = "checkpoints"
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    seed: int = 42


class BaseTrainer(ABC):
    """Trainer abstrait avec boucle d'entraînement standard.

    Les sous-classes implémentent `train_step` et `eval_step`
    pour leur modèle spécifique.
    """

    def __init__(self, model: nn.Module, config: TrainingConfig) -> None:
        self.model = model.to(config.device)
        self.config = config
        self.device = torch.device(config.device)

        torch.manual_seed(config.seed)

    @abstractmethod
    def train_step(self, batch: dict) -> float:
        """Effectue un pas d'entraînement.

        Returns:
            Valeur de la loss pour ce batch.
        """
        ...

    @abstractmethod
    def eval_step(self, batch: dict) -> dict[str, float]:
        """Effectue un pas d'évaluation.

        Returns:
            Dictionnaire de métriques.
        """
        ...

    def train(
        self,
        train_loader: DataLoader,
        eval_loader: DataLoader | None = None,
    ) -> dict[str, list[float]]:
        """Boucle d'entraînement complète.

        Args:
            train_loader: DataLoader d'entraînement.
            eval_loader: DataLoader d'évaluation (optionnel).

        Returns:
            Historique des métriques.
        """
        history: dict[str, list[float]] = {"train_loss": []}
        logger.info(
            "training.start",
            experiment=self.config.experiment_name,
            epochs=self.config.epochs,
            device=self.config.device,
        )

        for epoch in range(self.config.epochs):
            self.model.train()
            epoch_loss = 0.0
            num_batches = 0

            for batch in train_loader:
                loss = self.train_step(batch)
                epoch_loss += loss
                num_batches += 1

            avg_loss = epoch_loss / max(num_batches, 1)
            history["train_loss"].append(avg_loss)

            logger.info(
                "training.epoch",
                epoch=epoch + 1,
                loss=f"{avg_loss:.4f}",
            )

            # Évaluation
            if eval_loader is not None:
                metrics = self._evaluate(eval_loader)
                for key, value in metrics.items():
                    history.setdefault(key, []).append(value)

        logger.info("training.complete")
        return history

    def _evaluate(self, eval_loader: DataLoader) -> dict[str, float]:
        """Évalue le modèle sur un dataset de validation."""
        self.model.eval()
        all_metrics: dict[str, list[float]] = {}

        with torch.no_grad():
            for batch in eval_loader:
                metrics = self.eval_step(batch)
                for key, value in metrics.items():
                    all_metrics.setdefault(key, []).append(value)

        # Moyenne des métriques
        return {k: sum(v) / len(v) for k, v in all_metrics.items()}

    def save_checkpoint(self, path: str | Path) -> None:
        """Sauvegarde le modèle et l'état de l'entraînement."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"model_state_dict": self.model.state_dict(), "config": self.config},
            path,
        )
        logger.info("training.checkpoint_saved", path=str(path))
