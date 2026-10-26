"""n-grammes de caractères tf-idf."""

from __future__ import annotations

from collections import Counter

import numpy as np

from ml.models.intent_head.augment import plain


def char_grams(text: str, n_min: int = 2, n_max: int = 4) -> list[str]:
    """n-grammes par mot, bordés."""
    out: list[str] = []
    for word in plain(text).split():
        w = f" {word} "
        for n in range(n_min, n_max + 1):
            if len(w) < n:
                break
            out.extend(w[i : i + n] for i in range(len(w) - n + 1))
    return out


class CharNgrams:
    """tf-idf maison, sans sklearn."""

    def __init__(
        self,
        vocab: list[str] | None = None,
        idf: np.ndarray | None = None,
        n_min: int = 2,
        n_max: int = 4,
    ) -> None:
        self.n_min = n_min
        self.n_max = n_max
        self.vocab = list(vocab or [])
        self.index = {g: i for i, g in enumerate(self.vocab)}
        self.idf = np.asarray(idf if idf is not None else [], dtype=np.float32)

    def __len__(self) -> int:
        return len(self.vocab)

    def fit(self, texts: list[str], min_df: int = 2) -> CharNgrams:
        """vocab + idf du train."""
        df: Counter[str] = Counter()
        for t in texts:
            df.update(set(char_grams(t, self.n_min, self.n_max)))
        self.vocab = sorted(g for g, c in df.items() if c >= min_df)
        self.index = {g: i for i, g in enumerate(self.vocab)}
        n = len(texts)
        dfs = np.array([df[g] for g in self.vocab], dtype=np.float64)
        self.idf = (np.log((1 + n) / (1 + dfs)) + 1).astype(np.float32)
        return self

    def sparse_row(self, text: str) -> tuple[np.ndarray, np.ndarray]:
        """indices et poids l2."""
        counts = Counter(
            self.index[g] for g in char_grams(text, self.n_min, self.n_max) if g in self.index
        )
        if not counts:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)
        idx = np.fromiter(counts.keys(), dtype=np.int64, count=len(counts))
        tf = np.fromiter(counts.values(), dtype=np.float32, count=len(counts))
        val = (1 + np.log(tf)) * self.idf[idx]
        return idx, (val / np.linalg.norm(val)).astype(np.float32)

    def transform(self, texts: list[str]) -> object:
        """matrice creuse csr."""
        from scipy.sparse import csr_matrix

        indptr = [0]
        indices: list[np.ndarray] = []
        data: list[np.ndarray] = []
        for t in texts:
            idx, val = self.sparse_row(t)
            indices.append(idx)
            data.append(val)
            indptr.append(indptr[-1] + len(idx))
        return csr_matrix(
            (
                np.concatenate(data) if data else np.zeros(0, np.float32),
                np.concatenate(indices) if indices else np.zeros(0, np.int64),
                np.asarray(indptr),
            ),
            shape=(len(texts), len(self.vocab)),
            dtype=np.float32,
        )

    def logits(self, coef: np.ndarray, texts: list[str]) -> np.ndarray:
        """apport des n-grammes aux logits."""
        out = np.zeros((len(texts), coef.shape[0]), dtype=np.float32)
        for r, t in enumerate(texts):
            idx, val = self.sparse_row(t)
            if len(idx):
                out[r] = coef[:, idx] @ val
        return out
