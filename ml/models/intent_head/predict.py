"""intention par embeddings figés."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

from jenny.core.logging import get_logger
from ml.models.intent.config import INTENT_LABELS
from ml.models.intent.predict import IntentPredictor
from ml.models.intent_head.features import CharNgrams

logger = get_logger(__name__)

# encodeur épinglé, pas celui du rag
ENCODER_NAME = "paraphrase-multilingual-mpnet-base-v2"
DEFAULT_PATH = Path("checkpoints/intent_head/head.npz")
# npz sans pickle
FORMAT = "jenny-intent-head/2"

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


def sigmoid(z: np.ndarray) -> np.ndarray:
    """sigmoïde stable."""
    return 0.5 * (1.0 + np.tanh(0.5 * z))


def save_checkpoint(path: str | Path, arrays: dict[str, Any], config: dict) -> None:
    """tableaux + json, sans pickle."""
    data = {k: np.asarray(v) for k, v in arrays.items() if v is not None}
    for k, v in data.items():
        if v.dtype == object:
            raise TypeError(f"tableau objet refusé : {k}")
    data["config"] = np.asarray(json.dumps(config, ensure_ascii=False))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # fichier ouvert : pas de .npz ajouté
    with path.open("wb") as f:
        np.savez_compressed(f, **data)


def load_checkpoint(path: str | Path) -> tuple[dict[str, np.ndarray], dict]:
    """relit le npz, pickle interdit."""
    with np.load(Path(path), allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files if k != "config"}
        config = json.loads(str(z["config"])) if "config" in z.files else {}
    return arrays, config


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
        sec_coef: np.ndarray | None = None,
        sec_intercept: np.ndarray | None = None,
        sec_char_coef: np.ndarray | None = None,
        ovr_temperature: float = 1.0,
        multi_temperature: float = 1.0,
        second_floor: float = 0.35,
        ovr_threshold: float | None = None,
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
        # 14 un-contre-tous + multi
        self.ovr_temperature = float(ovr_temperature)
        self.multi_temperature = float(multi_temperature)
        self.second_floor = float(second_floor)
        # voie forte, sans détecteur
        self.ovr_threshold = None if ovr_threshold is None else float(ovr_threshold)
        self.has_secondary = sec_coef is not None
        w, b, wc = self.coef, self.intercept, self.char_coef
        if self.has_secondary:
            sc = np.asarray(sec_coef, dtype=np.float32)
            sb = np.asarray(sec_intercept, dtype=np.float32)
            if sc.shape != (n + 1, self.coef.shape[1]) or sb.shape != (n + 1,):
                raise ValueError("têtes secondaires incohérentes")
            if (sec_char_coef is None) != (self.char_coef is None):
                raise ValueError("n-grammes secondaires incohérents")
            w, b = np.vstack([w, sc]), np.concatenate([b, sb])
            if wc is not None:
                scc = np.asarray(sec_char_coef, dtype=np.float32)
                if scc.shape != (n + 1, wc.shape[1]):
                    raise ValueError("n-grammes secondaires incohérents")
                wc = np.vstack([wc, scc])
        # un seul produit par message
        self._w, self._b, self._wc = w, b, wc

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str | Path = DEFAULT_PATH, encoder: Any | None = None
    ) -> EmbeddingIntentPredictor:
        """charge la tête + l'encodeur."""
        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint non trouvé : {path}")
        arr, cfg = load_checkpoint(path)
        if cfg.get("format") != FORMAT:
            raise ValueError(f"format inconnu : {cfg.get('format')}")
        if cfg.get("encoder") != ENCODER_NAME:
            raise ValueError(f"encodeur inattendu : {cfg.get('encoder')}")
        enc = encoder if encoder is not None else get_encoder(ENCODER_NAME)
        dim = int(arr["coef"].shape[1])
        get_dim = getattr(enc, "get_embedding_dimension", None) or getattr(
            enc, "get_sentence_embedding_dimension", None
        )
        if get_dim is not None and int(get_dim()) != dim:
            raise ValueError("dimension d'embedding incohérente")
        chars = None
        if "char_coef" in arr:
            n_min, n_max = cfg.get("char_ngram") or (2, 4)
            chars = CharNgrams(arr["char_vocab"].tolist(), arr["char_idf"], int(n_min), int(n_max))
        pred = cls(
            enc,
            arr["coef"],
            arr["intercept"],
            temperature=cfg.get("temperature", 1.0),
            multi_threshold=cfg.get("multi_threshold", 0.35),
            max_intents=cfg.get("max_intents", 3),
            clarify_threshold=cfg.get("clarify_threshold", 0.5),
            labels=arr["labels"].tolist() if "labels" in arr else None,
            chars=chars,
            char_coef=arr.get("char_coef"),
            sec_coef=arr.get("sec_coef"),
            sec_intercept=arr.get("sec_intercept"),
            sec_char_coef=arr.get("sec_char_coef"),
            ovr_temperature=cfg.get("ovr_temperature", 1.0),
            multi_temperature=cfg.get("multi_temperature", 1.0),
            second_floor=cfg.get("second_floor", 0.35),
            ovr_threshold=cfg.get("ovr_threshold"),
            meta=cfg.get("meta"),
        )
        logger.info("intent_head.predictor.loaded", path=str(path), t=round(pred.temperature, 3))
        return pred

    def scores(
        self, embeddings: np.ndarray, texts: list[str]
    ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
        """softmax, un-contre-tous, multi."""
        logits = embeddings @ self._w.T + self._b
        if self.chars is not None and self._wc is not None:
            logits = logits + self.chars.logits(self._wc, texts)
        n = len(self.labels)
        probs = softmax(logits[:, :n] / self.temperature)
        if not self.has_secondary:
            return probs, None, None
        ovr = sigmoid(logits[:, n : 2 * n] / self.ovr_temperature)
        multi = sigmoid(logits[:, 2 * n] / self.multi_temperature)
        return probs, ovr, multi

    def proba(self, embeddings: np.ndarray, texts: list[str]) -> np.ndarray:
        """probas calibrées."""
        return self.scores(embeddings, texts)[0]

    def _format(
        self, probs: np.ndarray, ovr: np.ndarray | None = None, multi: float | None = None
    ) -> dict:
        """même dict que le lstm."""
        all_scores = {lab: round(float(p), 4) for lab, p in zip(self.labels, probs, strict=True)}
        order = np.argsort(-probs, kind="stable")
        top = int(order[0])
        p1 = float(probs[top])
        detected = [{"intent": self.labels[top], "confidence": round(p1, 4)}]
        if ovr is None or multi is None:
            # ancien repli softmax
            for j in order[1 : self.max_intents]:
                score = float(probs[int(j)])
                if score < self.multi_threshold:
                    break
                detected.append({"intent": self.labels[int(j)], "confidence": round(score, 4)})
        else:
            is_multi = float(multi) >= self.multi_threshold
            extra = [int(j) for j in np.argsort(-ovr, kind="stable") if int(j) != top]
            for j in extra[: self.max_intents - 1]:
                score = float(ovr[j])
                # détecteur multi ou score fort
                strong = self.ovr_threshold is not None and score >= self.ovr_threshold
                if score < self.second_floor or not (is_multi or strong):
                    break
                # jamais au-dessus du primaire
                detected.append({"intent": self.labels[j], "confidence": round(min(score, p1), 4)})
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
        return self.predict_batch_multi([text or ""])[0]

    def predict_batch_multi(self, texts: list[str]) -> list[dict]:
        """batch multi-label."""
        if not texts:
            return []
        texts = [t or "" for t in texts]
        probs, ovr, multi = self.scores(encode(self.encoder, texts), texts)
        if ovr is None or multi is None:
            return [self._format(p) for p in probs]
        return [self._format(p, o, float(m)) for p, o, m in zip(probs, ovr, multi, strict=True)]

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
