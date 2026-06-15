"""Intégration MLflow pour le tracking des expériences.

Encapsule MLflow pour un usage simple et cohérent
dans tout le projet Jenny.
"""

from pathlib import Path
from typing import Any

import mlflow

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)


class ExperimentTracker:
    """Wrapper MLflow pour le tracking d'expériences.

    Centralise la configuration MLflow et fournit
    des méthodes simples pour logger métriques,
    paramètres et artefacts.
    """

    def __init__(self, experiment_name: str) -> None:
        settings = get_settings()
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(experiment_name)
        self.experiment_name = experiment_name
        logger.info("mlflow.init", experiment=experiment_name)

    def start_run(self, run_name: str | None = None) -> mlflow.ActiveRun:
        """Démarre un nouveau run MLflow.

        Args:
            run_name: Nom optionnel du run.
        """
        return mlflow.start_run(run_name=run_name)

    @staticmethod
    def log_params(params: dict[str, Any]) -> None:
        """Logue les hyperparamètres du run."""
        mlflow.log_params(params)

    @staticmethod
    def log_metrics(metrics: dict[str, float], step: int | None = None) -> None:
        """Logue les métriques du run.

        Args:
            metrics: Dictionnaire de métriques.
            step: Numéro d'itération/epoch.
        """
        mlflow.log_metrics(metrics, step=step)

    @staticmethod
    def log_artifact(path: str | Path) -> None:
        """Logue un fichier artefact (modèle, plot, etc.)."""
        mlflow.log_artifact(str(path))

    @staticmethod
    def log_model(model: Any, artifact_path: str = "model") -> None:
        """Logue un modèle PyTorch via MLflow.

        TODO: utiliser mlflow.pytorch.log_model pour les modèles PyTorch.
        """
        mlflow.pytorch.log_model(model, artifact_path)

    @staticmethod
    def end_run() -> None:
        """Termine le run actif."""
        mlflow.end_run()
