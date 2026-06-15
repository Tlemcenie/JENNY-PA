"""Feature engineering pour les modèles ML.

Transforme les données brutes (messages) en features
exploitables par les modèles de classification et scoring.
"""

from dataclasses import dataclass

from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MessageFeatures:
    """Features extraites d'un message client."""

    text_length: int
    word_count: int
    has_question_mark: bool
    has_exclamation: bool
    has_url: bool
    channel: str
    hour_of_day: int | None = None
    # TODO: ajouter des features NLP (sentiment, entities, language...)


class FeatureExtractor:
    """Extracteur de features à partir de messages bruts.

    Transforme un message texte en un vecteur de features
    utilisable par les modèles ML supervisés.
    """

    def extract(self, content: str, channel: str) -> MessageFeatures:
        """Extrait les features d'un message.

        Args:
            content: Contenu textuel du message.
            channel: Canal source du message.

        Returns:
            Features structurées.
        """
        words = content.split()
        features = MessageFeatures(
            text_length=len(content),
            word_count=len(words),
            has_question_mark="?" in content,
            has_exclamation="!" in content,
            has_url="http" in content.lower(),
            channel=channel,
        )
        logger.debug(
            "features.extracted",
            text_length=features.text_length,
            word_count=features.word_count,
        )
        return features

    def to_vector(self, features: MessageFeatures) -> list[float]:
        """Convertit les features en vecteur numérique.

        TODO: normalisation, encoding catégoriel, etc.
        """
        return [
            float(features.text_length),
            float(features.word_count),
            float(features.has_question_mark),
            float(features.has_exclamation),
            float(features.has_url),
        ]
