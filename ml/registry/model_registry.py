"""Registry de modèles ML.

Gère le versioning et le déploiement des modèles
via MLflow Model Registry.
"""

import mlflow
from mlflow.tracking import MlflowClient

from jenny.core.logging import get_logger

logger = get_logger(__name__)


class ModelRegistry:
    """Gestionnaire du registry de modèles MLflow.

    Permet d'enregistrer, versionner et promouvoir
    des modèles pour la production.

    TODO: implémenter les workflows de promotion
          (staging → production).
    """

    def __init__(self) -> None:
        self.client = MlflowClient()

    def register_model(self, run_id: str, model_name: str) -> str:
        """Enregistre un modèle depuis un run MLflow.

        Args:
            run_id: ID du run contenant le modèle.
            model_name: Nom sous lequel enregistrer le modèle.

        Returns:
            Version du modèle enregistré.
        """
        model_uri = f"runs:/{run_id}/model"
        result = mlflow.register_model(model_uri, model_name)
        logger.info(
            "registry.registered",
            model=model_name,
            version=result.version,
        )
        return result.version

    def get_latest_version(
        self,
        model_name: str,
        stage: str = "Production",
    ) -> str | None:
        """Récupère la dernière version d'un modèle en production.

        Args:
            model_name: Nom du modèle.
            stage: Stage MLflow (Staging, Production, Archived).

        Returns:
            Numéro de version ou None.
        """
        versions = self.client.get_latest_versions(model_name, stages=[stage])
        if versions:
            return versions[0].version
        return None

    def load_production_model(self, model_name: str) -> object:
        """Charge le modèle en production.

        Args:
            model_name: Nom du modèle.

        Returns:
            Modèle chargé prêt pour l'inférence.
        """
        model_uri = f"models:/{model_name}/Production"
        model = mlflow.pytorch.load_model(model_uri)
        logger.info("registry.loaded", model=model_name)
        return model
