"""Évaluation des modèles ML.

Fournit des métriques standardisées pour évaluer
les performances des modèles Jenny.
"""

from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EvaluationResult:
    """Résultat d'une évaluation de modèle."""

    model_name: str
    dataset_name: str
    metrics: dict[str, float]
    num_samples: int


class ModelEvaluator:
    """Évaluateur générique pour les modèles Jenny.

    Calcule les métriques de classification et de génération
    selon le type de tâche.

    TODO: implémenter les métriques spécifiques
          (accuracy, F1, BLEU, perplexity...).
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def evaluate_classification(
        self,
        predictions: list[str],
        ground_truth: list[str],
    ) -> EvaluationResult:
        """Évalue un modèle de classification.

        Args:
            predictions: Labels prédits.
            ground_truth: Labels réels.

        Returns:
            Métriques de classification.
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("predictions et ground_truth doivent avoir la même taille")

        correct = sum(p == g for p, g in zip(predictions, ground_truth, strict=True))
        accuracy = correct / len(predictions) if predictions else 0.0

        result = EvaluationResult(
            model_name=self.model_name,
            dataset_name="eval",
            metrics={"accuracy": accuracy},
            num_samples=len(predictions),
        )
        logger.info("eval.classification", **result.metrics, num_samples=result.num_samples)
        return result

    def evaluate_generation(
        self,
        generated: list[str],
        references: list[str],
    ) -> EvaluationResult:
        """Évalue un modèle de génération de texte.

        TODO: implémenter BLEU, ROUGE, perplexity.
        """
        result = EvaluationResult(
            model_name=self.model_name,
            dataset_name="eval",
            metrics={"placeholder_score": 0.0},
            num_samples=len(generated),
        )
        logger.info("eval.generation", num_samples=result.num_samples)
        return result
