"""Inférence du modèle NER BiGRU.

Charge le modèle entraîné et extrait les entités
d'un message texte au format structuré.
"""

from __future__ import annotations

from pathlib import Path

import torch

from jenny.core.logging import get_logger
from ml.models.ner.config import ID_TO_TAG, NERModelConfig
from ml.models.ner.model import BiGRUNER

logger = get_logger(__name__)


class NERPredictor:
    """Extracteur d'entités à partir d'un checkpoint BiGRU.

    Charge le modèle entraîné et fournit une interface simple
    pour extraire les entités nommées d'un message texte.
    """

    def __init__(
        self,
        model: BiGRUNER,
        vocab: dict[str, int],
        config: NERModelConfig,
    ) -> None:
        self.model = model
        self.vocab = vocab
        self.config = config
        self.model.eval()

    @classmethod
    def from_checkpoint(cls, checkpoint_path: str | Path) -> NERPredictor:
        """Charge un prédicteur depuis un checkpoint."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint NER non trouvé : {path}")

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        config = checkpoint["config"]
        vocab = checkpoint["vocab"]

        model = BiGRUNER(config)
        model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(config.device)
        model.eval()

        logger.info("ner.predictor.loaded", path=str(path))
        return cls(model, vocab, config)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize simple par espaces."""
        return text.strip().split()

    def _encode(self, tokens: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
        """Encode une séquence de tokens."""
        ids = [self.vocab.get(t.lower(), 1) for t in tokens]

        if len(ids) > self.config.max_seq_length:
            ids = ids[: self.config.max_seq_length]

        padding = self.config.max_seq_length - len(ids)
        mask = [1] * len(ids) + [0] * padding
        ids = ids + [0] * padding

        return (
            torch.tensor([ids], dtype=torch.long),
            torch.tensor([mask], dtype=torch.long),
        )

    @torch.no_grad()
    def predict(self, text: str) -> dict[str, str]:
        """Extrait les entités d'un message.

        Args:
            text: Message texte à analyser.

        Returns:
            Dictionnaire {nom_entité: valeur} ex: {"order_number": "CMD-123"}
        """
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        input_ids, attention_mask = self._encode(tokens)
        input_ids = input_ids.to(self.config.device)
        attention_mask = attention_mask.to(self.config.device)

        pred_tags = self.model.predict_tags(input_ids, attention_mask)
        pred_tags = pred_tags[0].cpu().tolist()

        # Décoder les tags BIO en entités
        return self._decode_bio(tokens, pred_tags[: len(tokens)])

    def _decode_bio(self, tokens: list[str], tag_ids: list[int]) -> dict[str, str]:
        """Décode les tags BIO en entités structurées.

        Regroupe les tokens B- et I- consécutifs du même type.
        """
        entities: dict[str, str] = {}
        current_entity: str | None = None
        current_tokens: list[str] = []

        for token, tag_id in zip(tokens, tag_ids, strict=False):
            tag = ID_TO_TAG.get(tag_id, "O")

            if tag.startswith("B-"):
                # Sauvegarder l'entité précédente
                if current_entity and current_tokens:
                    entity_key = current_entity.lower()
                    entities[entity_key] = " ".join(current_tokens)

                current_entity = tag[2:]  # Retirer "B-"
                current_tokens = [token]

            elif tag.startswith("I-") and current_entity == tag[2:]:
                # Continuer l'entité courante
                current_tokens.append(token)

            else:
                # Tag "O" ou changement d'entité
                if current_entity and current_tokens:
                    entity_key = current_entity.lower()
                    entities[entity_key] = " ".join(current_tokens)
                current_entity = None
                current_tokens = []

        # Dernière entité
        if current_entity and current_tokens:
            entity_key = current_entity.lower()
            entities[entity_key] = " ".join(current_tokens)

        return entities

    @torch.no_grad()
    def predict_with_tags(self, text: str) -> list[tuple[str, str]]:
        """Retourne les tokens avec leurs tags BIO.

        Utile pour le debug et la visualisation.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return []

        input_ids, attention_mask = self._encode(tokens)
        input_ids = input_ids.to(self.config.device)
        attention_mask = attention_mask.to(self.config.device)

        pred_tags = self.model.predict_tags(input_ids, attention_mask)
        pred_tags = pred_tags[0].cpu().tolist()

        return [
            (token, ID_TO_TAG.get(tag_id, "O"))
            for token, tag_id in zip(tokens, pred_tags[: len(tokens)], strict=False)
        ]
