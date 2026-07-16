"""inférence du modèle NER."""

from __future__ import annotations

from pathlib import Path

import torch

from jenny.core.logging import get_logger
from ml.models.ner.config import ID_TO_TAG, NERModelConfig
from ml.models.ner.model import BiGRUNER

logger = get_logger(__name__)


class NERPredictor:
    """extracteur d'entités BiGRU."""

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
        """charge depuis un checkpoint."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint NER non trouvé : {path}")

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        config = checkpoint["config"]
        vocab = checkpoint["vocab"]

        # re-résout le device au runtime
        if torch.cuda.is_available():
            config.device = "cuda"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            config.device = "mps"
        else:
            config.device = "cpu"

        model = BiGRUNER(config)
        model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(config.device)
        model.eval()

        logger.info("ner.predictor.loaded", path=str(path))
        return cls(model, vocab, config)

    def _tokenize(self, text: str) -> list[str]:
        """tokenize par espaces."""
        return text.strip().split()

    def _encode(self, tokens: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
        """encode les tokens."""
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
        """extrait les entités."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        input_ids, attention_mask = self._encode(tokens)
        input_ids = input_ids.to(self.config.device)
        attention_mask = attention_mask.to(self.config.device)

        pred_tags = self.model.predict_tags(input_ids, attention_mask)
        pred_tags = pred_tags[0].cpu().tolist()

        # décode les tags BIO
        return self._decode_bio(tokens, pred_tags[: len(tokens)])

    def _decode_bio(self, tokens: list[str], tag_ids: list[int]) -> dict[str, str]:
        """tags BIO vers entités."""
        entities: dict[str, str] = {}
        current_entity: str | None = None
        current_tokens: list[str] = []

        for token, tag_id in zip(tokens, tag_ids, strict=False):
            tag = ID_TO_TAG.get(tag_id, "O")

            if tag.startswith("B-"):
                # sauve l'entité précédente
                if current_entity and current_tokens:
                    entity_key = current_entity.lower()
                    entities[entity_key] = " ".join(current_tokens)

                current_entity = tag[2:]  # enlève le "B-"
                current_tokens = [token]

            elif tag.startswith("I-") and current_entity == tag[2:]:
                # continue l'entité
                current_tokens.append(token)

            else:
                # tag O ou changement
                if current_entity and current_tokens:
                    entity_key = current_entity.lower()
                    entities[entity_key] = " ".join(current_tokens)
                current_entity = None
                current_tokens = []

        # dernière entité
        if current_entity and current_tokens:
            entity_key = current_entity.lower()
            entities[entity_key] = " ".join(current_tokens)

        return entities

    @torch.no_grad()
    def predict_with_tags(self, text: str) -> list[tuple[str, str]]:
        """tokens avec leurs tags."""
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
