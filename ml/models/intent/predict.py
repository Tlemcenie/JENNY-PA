"""Inférence du classifieur d'intention — Multi-Label.

Charge le modèle entraîné et prédit UNE ou PLUSIEURS intentions
d'un message texte.

Ex: "RDV urgent et devis" → [
    {"intent": "appointment", "confidence": 0.85},
    {"intent": "quote", "confidence": 0.72},
]
"""

from __future__ import annotations

from pathlib import Path

import torch

from jenny.core.logging import get_logger
from ml.models.intent.config import ID_TO_LABEL, IntentModelConfig
from ml.models.intent.model import IntentClassifier

logger = get_logger(__name__)


class IntentPredictor:
    """Prédicteur d'intention multi-label à partir d'un checkpoint.

    Charge le modèle LSTM entraîné et fournit une interface
    pour prédire UNE ou PLUSIEURS intentions d'un message.
    """

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
        """Charge un prédicteur depuis un checkpoint."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint non trouvé : {path}")

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        config = checkpoint["config"]
        vocab = checkpoint["vocab"]

        model = IntentClassifier(config)
        model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(config.device)
        model.eval()

        logger.info("intent.predictor.loaded", path=str(path))
        return cls(model, vocab, config)

    def _encode(self, text: str) -> tuple[torch.Tensor, torch.Tensor]:
        """Encode un texte en tenseurs pour le modèle."""
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
        """Prédit l'intention principale (rétro-compatible).

        Retourne la même structure qu'avant pour ne rien casser.

        Returns:
            {"intent": str, "confidence": float, "all_scores": dict}
        """
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
        """Prédit TOUTES les intentions détectées (multi-label).

        Utilise sigmoid : chaque intention a un score indépendant.
        Seules celles au-dessus du seuil sont retournées.

        Args:
            text: Message texte à classifier.

        Returns:
            {
                "intents": [
                    {"intent": "appointment", "confidence": 0.85},
                    {"intent": "quote", "confidence": 0.72},
                ],
                "primary_intent": "appointment",
                "primary_confidence": 0.85,
                "is_multi_intent": True,
                "all_scores": {"appointment": 0.85, "quote": 0.72, ...},
                "needs_clarification": False,
            }
        """
        input_ids, attention_mask = self._encode(text)
        input_ids = input_ids.to(self.config.device)
        attention_mask = attention_mask.to(self.config.device)

        # Sigmoid pour scores indépendants
        probs = self.model.predict_proba(input_ids, attention_mask)
        probs = probs[0]  # Premier (seul) élément du batch

        threshold = getattr(self.config, "multi_label_threshold", 0.35)
        max_intents = getattr(self.config, "max_intents", 3)

        # Tous les scores
        all_scores = {
            ID_TO_LABEL.get(i, f"unknown_{i}"): round(p.item(), 4) for i, p in enumerate(probs)
        }

        # Filtrer par seuil + trier par confiance
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

        # Trier par confiance décroissante et limiter
        detected.sort(key=lambda x: x["confidence"], reverse=True)
        detected = detected[:max_intents]

        # Si rien n'est au-dessus du seuil, prendre le top-1
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

        # Déterminer si Jenny devrait demander une clarification
        needs_clarification = False
        if primary["confidence"] < 0.5:
            needs_clarification = True
        elif is_multi and detected[1]["confidence"] > 0.6:
            # Deux intentions fortes → peut-être clarifier la priorité
            needs_clarification = False  # On traite les deux

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
        """Prédit les intentions pour un batch de messages."""
        return [self.predict(text) for text in texts]

    @torch.no_grad()
    def predict_batch_multi(self, texts: list[str]) -> list[dict]:
        """Prédit les intentions multi-label pour un batch de messages."""
        return [self.predict_multi(text) for text in texts]
