"""intention par embeddings figés."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from jenny.core.logging import get_logger
from ml.models.intent.config import INTENT_LABELS
from ml.models.intent.predict import IntentPredictor
from ml.models.intent_head.features import CharNgrams

logger = get_logger(__name__)

# encodeur épinglé, pas celui du rag
ENCODER_NAME = "paraphrase-multilingual-mpnet-base-v2"
DEFAULT_PATH = Path("checkpoints/intent_head/head.joblib")
FORMAT = "jenny-intent-head/1"

_ENCODERS: dict[tuple[str, str | None], Any] = {}
_ENCODERS_LOCK = threading.Lock()


def get_encoder(name: str = ENCODER_NAME, device: str | None = None) -> Any:
    """encodeur partagé, chargé une fois."""
    key = (name, device)
    with _ENCODERS_LOCK:
        enc = _ENCODERS.get(key)
        if enc is None:
            from sentence_transformers import SentenceTransformer

            enc = SentenceTransformer(name, device=device)
            _ENCODERS[key] = enc
            logger.info("intent_head.encoder.loaded", model=name, device=str(enc.device))
    return enc


def encode(encoder: Any, texts: list[str], batch_size: int = 64) -> np.ndarray:
    """embeddings normalisés."""
    vecs = encoder.encode(
        [t or " " for t in texts],
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vecs, dtype=np.float32)


def softmax(logits: np.ndarray) -> np.ndarray:
    """softmax stable."""
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class EmbeddingIntentPredictor(IntentPredictor):
    """tête logistique sur mpnet figé."""

    def __init__(
        self,
        encoder: Any,
        coef: np.ndarray,
        intercept: np.ndarray,
        *,
        temperature: float = 1.0,
        multi_threshold: float = 0.35,
        max_intents: int = 3,
        clarify_threshold: float = 0.5,
        labels: list[str] | None = None,
        chars: CharNgrams | None = None,
        char_coef: np.ndarray | None = None,
        meta: dict | None = None,
    ) -> None:
        # pas de lstm ici
        self.model = None
        self.vocab: dict[str, int] = {}
        self.config = None
        self.encoder = encoder
        self.coef = np.asarray(coef, dtype=np.float32)
        self.intercept = np.asarray(intercept, dtype=np.float32)
        self.temperature = float(temperature)
        self.multi_threshold = float(multi_threshold)
        self.max_intents = int(max_intents)
        self.clarify_threshold = float(clarify_threshold)
        self.labels = list(labels or INTENT_LABELS)
        self.meta = meta or {}
        # bloc n-grammes optionnel
        self.chars = chars if char_coef is not None else None
        self.char_coef = None if char_coef is None else np.asarray(char_coef, dtype=np.float32)
        if self.labels != INTENT_LABELS:
            raise ValueError("taxonomie différente du moteur")
        n = len(self.labels)
        if self.coef.ndim != 2 or self.coef.shape[0] != n or self.intercept.shape != (n,):
            raise ValueError("poids incohérents")
        if self.char_coef is not None and (
            self.chars is None or self.char_coef.shape != (n, len(self.chars))
        ):
            raise ValueError("bloc n-grammes incohérent")

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str | Path = DEFAULT_PATH, encoder: Any | None = None
    ) -> EmbeddingIntentPredictor:
        """charge la tête + l'encodeur."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint non trouvé : {path}")
        ckpt = joblib.load(path)
        if ckpt.get("format") != FORMAT:
            raise ValueError(f"format inconnu : {ckpt.get('format')}")
        if ckpt.get("encoder") != ENCODER_NAME:
            raise ValueError(f"encodeur inattendu : {ckpt.get('encoder')}")
        enc = encoder if encoder is not None else get_encoder(ENCODER_NAME)
        dim = int(np.asarray(ckpt["coef"]).shape[1])
        get_dim = getattr(enc, "get_embedding_dimension", None) or getattr(
            enc, "get_sentence_embedding_dimension", None
        )
        if get_dim is not None and int(get_dim()) != dim:
            raise ValueError("dimension d'embedding incohérente")
        chars = None
        if ckpt.get("char_coef") is not None:
            n_min, n_max = ckpt.get("char_ngram") or (2, 4)
            chars = CharNgrams(ckpt["char_vocab"], ckpt["char_idf"], int(n_min), int(n_max))
        pred = cls(
            enc,
            ckpt["coef"],
            ckpt["intercept"],
            temperature=ckpt.get("temperature", 1.0),
            multi_threshold=ckpt.get("multi_threshold", 0.35),
            max_intents=ckpt.get("max_intents", 3),
            clarify_threshold=ckpt.get("clarify_threshold", 0.5),
            labels=ckpt.get("labels"),
            chars=chars,
            char_coef=ckpt.get("char_coef"),
            meta=ckpt.get("meta"),
        )
        logger.info("intent_head.predictor.loaded", path=str(path), t=round(pred.temperature, 3))
        return pred

    def proba(self, embeddings: np.ndarray, texts: list[str]) -> np.ndarray:
        """probas calibrées."""
        logits = embeddings @ self.coef.T + self.intercept
        if self.chars is not None and self.char_coef is not None:
            logits = logits + self.chars.logits(self.char_coef, texts)
        return softmax(logits / self.temperature)

    def _format(self, probs: np.ndarray) -> dict:
        """même dict que le lstm."""
        all_scores = {lab: round(float(p), 4) for lab, p in zip(self.labels, probs, strict=True)}
        order = np.argsort(-probs, kind="stable")
        top = int(order[0])
        detected = [{"intent": self.labels[top], "confidence": round(float(probs[top]), 4)}]
        for j in order[1 : self.max_intents]:
            score = float(probs[int(j)])
            if score < self.multi_threshold:
                break
            detected.append({"intent": self.labels[int(j)], "confidence": round(score, 4)})
        primary = detected[0]
        return {
            "intents": detected,
            "primary_intent": primary["intent"],
            "primary_confidence": primary["confidence"],
            "is_multi_intent": len(detected) > 1,
            "all_scores": all_scores,
            "needs_clarification": primary["confidence"] < self.clarify_threshold,
        }

    def predict_multi(self, text: str) -> dict:
        """prédit toutes les intentions."""
        texts = [text or ""]
        return self._format(self.proba(encode(self.encoder, texts), texts)[0])

    def predict_batch_multi(self, texts: list[str]) -> list[dict]:
        """batch multi-label."""
        if not texts:
            return []
        texts = [t or "" for t in texts]
        probs = self.proba(encode(self.encoder, texts), texts)
        return [self._format(p) for p in probs]

    def predict_batch(self, texts: list[str]) -> list[dict[str, object]]:
        """prédit un batch."""
        out: list[dict[str, object]] = []
        for res in self.predict_batch_multi(texts):
            out.append(
                {
                    "intent": res["primary_intent"],
                    "confidence": res["primary_confidence"],
                    "all_scores": res["all_scores"],
                }
            )
        return out
