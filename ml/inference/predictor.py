"""Inférence des modèles ML en production.

Charge un modèle depuis un checkpoint et fournit
une interface simple pour les prédictions.
"""

from pathlib import Path

import torch
from torch import nn

from jenny.core.logging import get_logger

logger = get_logger(__name__)


class ModelPredictor:
    """Chargement et inférence d'un modèle PyTorch.

    Gère le chargement du checkpoint, le device mapping
    et l'inférence batch/unitaire.
    """

    def __init__(self, model: nn.Module, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(self.device)
        self.model.eval()

    @classmethod
    def from_checkpoint(cls, model: nn.Module, checkpoint_path: str | Path) -> "ModelPredictor":
        """Charge un modèle depuis un checkpoint sauvegardé.

        Args:
            model: Instance du modèle (architecture).
            checkpoint_path: Chemin vers le fichier .pt.
        """
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint non trouvé : {path}")

        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        model.load_state_dict(checkpoint["model_state_dict"])
        logger.info("predictor.loaded", checkpoint=str(path))
        return cls(model)

    @torch.no_grad()
    def predict(self, inputs: torch.Tensor) -> torch.Tensor:
        """Effectue une prédiction.

        Args:
            inputs: Tensor d'entrée.

        Returns:
            Tensor de sortie (logits ou probas selon le modèle).
        """
        inputs = inputs.to(self.device)
        return self.model(inputs)

    @torch.no_grad()
    def predict_batch(self, batch: list[torch.Tensor]) -> list[torch.Tensor]:
        """Prédictions sur un batch de tenseurs."""
        return [self.predict(x) for x in batch]
