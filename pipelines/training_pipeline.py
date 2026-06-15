"""Pipeline d'entraînement ML.

Orchestre le cycle complet d'entraînement :
données → features → train → eval → register.
"""

from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TrainingPipelineConfig:
    """Configuration du pipeline d'entraînement."""

    experiment_name: str = "jenny-training"
    model_type: str = "classifier"
    data_path: str = "data/processed"
    epochs: int = 10
    register_model: bool = False


class TrainingPipeline:
    """Pipeline d'entraînement de bout en bout.

    Étapes :
    1. Chargement des données processed
    2. Feature engineering
    3. Split train/eval
    4. Entraînement avec tracking MLflow
    5. Évaluation
    6. Enregistrement du modèle (optionnel)

    TODO: implémenter les étapes réelles.
    """

    def __init__(self, config: TrainingPipelineConfig) -> None:
        self.config = config

    async def run(self) -> dict[str, object]:
        """Exécute le pipeline d'entraînement complet.

        Returns:
            Résultats (métriques, run_id, etc.).
        """
        logger.info(
            "pipeline.training.start",
            experiment=self.config.experiment_name,
            model_type=self.config.model_type,
        )

        # TODO: implémenter les étapes réelles
        steps = [
            "load_data",
            "extract_features",
            "split_data",
            "train_model",
            "evaluate_model",
        ]
        for step in steps:
            logger.info("pipeline.training.step", step=step, status="placeholder")

        if self.config.register_model:
            logger.info("pipeline.training.register", status="placeholder")

        logger.info("pipeline.training.complete")
        return {"status": "placeholder", "experiment": self.config.experiment_name}
