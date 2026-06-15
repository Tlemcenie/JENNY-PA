"""Pipeline d'inférence.

Orchestre l'inférence en production :
message → features → prédiction → post-processing.
"""

from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class InferenceRequest:
    """Requête d'inférence."""

    message_id: str
    content: str
    channel: str


@dataclass
class InferenceResult:
    """Résultat d'inférence."""

    message_id: str
    category: str | None = None
    priority: int | None = None
    confidence: float = 0.0
    suggested_reply: str | None = None


class InferencePipeline:
    """Pipeline d'inférence pour les messages entrants.

    Étapes :
    1. Feature extraction
    2. Prédiction (classification, priorité)
    3. Génération de réponse (RAG / agent)
    4. Post-processing et formatage

    TODO: brancher les vrais modèles.
    """

    async def predict(self, request: InferenceRequest) -> InferenceResult:
        """Effectue une inférence complète sur un message.

        Args:
            request: Requête contenant le message à traiter.

        Returns:
            Résultat avec catégorie, priorité et réponse suggérée.
        """
        logger.info(
            "pipeline.inference.predict",
            message_id=request.message_id,
            channel=request.channel,
        )

        # TODO: remplacer par de vrais modèles
        return InferenceResult(
            message_id=request.message_id,
            category="general",
            priority=3,
            confidence=0.0,
            suggested_reply=None,
        )
