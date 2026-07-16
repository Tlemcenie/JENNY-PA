"""inférence intent multi-label."""

from __future__ import annotations

from pathlib import Path

import torch

from jenny.core.logging import get_logger
from ml.models.intent.config import ID_TO_LABEL, IntentModelConfig
from ml.models.intent.model import IntentClassifier

logger = get_logger(__name__)


class IntentPredictor:
    """prédicteur d'intention."""

    def __init__(
        self,
        model: IntentClassifier,
        vocab: dict[str, int],
        config: IntentModelConfig,
    ) -> None:
        self.model = model
        self.vocab = vocab
        self.config = config
        self.model.eval()

    @classmethod
    def from_checkpoint(cls, checkpoint_path: str | Path) -> IntentPredictor:
        """charge depuis un checkpoint."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint non trouvé : {path}")

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        config = checkpoint["config"]
        vocab = checkpoint["vocab"]

        # re-résout le device
        if torch.cuda.is_available():
            config.device = "cuda"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            config.device = "mps"
        else:
            config.device = "cpu"

        model = IntentClassifier(config)
        model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(config.device)
        model.eval()

        logger.info("intent.predictor.loaded", path=str(path))
        return cls(model, vocab, config)

    def _encode(self, text: str) -> tuple[torch.Tensor, torch.Tensor]:
        """encode le texte."""
        tokens = text.lower().strip().split()
        ids = [self.vocab.get(t, 1) for t in tokens]  # 1 = <UNK>

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
    def predict(self, text: str) -> dict[str, object]:
        """prédit l'intention principale."""
        result = self.predict_multi(text)
        top = (
            result["intents"][0] if result["intents"] else {"intent": "general", "confidence": 0.0}
        )

        return {
            "intent": top["intent"],
            "confidence": top["confidence"],
            "all_scores": result["all_scores"],
        }

    @torch.no_grad()
    def predict_multi(self, text: str) -> dict:
        """prédit toutes les intentions."""
        input_ids, attention_mask = self._encode(text)
        input_ids = input_ids.to(self.config.device)
        attention_mask = attention_mask.to(self.config.device)

        # sigmoid pour scores indépendants
        probs = self.model.predict_proba(input_ids, attention_mask)
        probs = probs[0]  # premier du batch

        threshold = getattr(self.config, "multi_label_threshold", 0.35)
        max_intents = getattr(self.config, "max_intents", 3)

        # tous les scores
        all_scores = {
            ID_TO_LABEL.get(i, f"unknown_{i}"): round(p.item(), 4) for i, p in enumerate(probs)
        }

        # filtre par seuil
        detected = []
        for i, p in enumerate(probs):
            score = p.item()
            if score >= threshold:
                detected.append(
                    {
                        "intent": ID_TO_LABEL.get(i, "general"),
                        "confidence": round(score, 4),
                    }
                )

        # trie et limite
        detected.sort(key=lambda x: x["confidence"], reverse=True)
        detected = detected[:max_intents]

        # fallback sur le top-1
        if not detected:
            top_idx = probs.argmax().item()
            detected = [
                {
                    "intent": ID_TO_LABEL.get(top_idx, "general"),
                    "confidence": round(probs[top_idx].item(), 4),
                }
            ]

        primary = detected[0]
        is_multi = len(detected) > 1

        # clarification nécessaire ?
        needs_clarification = False
        if primary["confidence"] < 0.5:
            needs_clarification = True
        elif is_multi and detected[1]["confidence"] > 0.6:
            # deux intentions fortes
            needs_clarification = False  # on traite les deux

        return {
            "intents": detected,
            "primary_intent": primary["intent"],
            "primary_confidence": primary["confidence"],
            "is_multi_intent": is_multi,
            "all_scores": all_scores,
            "needs_clarification": needs_clarification,
        }

    @torch.no_grad()
    def predict_batch(self, texts: list[str]) -> list[dict[str, object]]:
        """prédit un batch."""
        return [self.predict(text) for text in texts]

    @torch.no_grad()
    def predict_batch_multi(self, texts: list[str]) -> list[dict]:
        """batch multi-label."""
        return [self.predict_multi(text) for text in texts]
