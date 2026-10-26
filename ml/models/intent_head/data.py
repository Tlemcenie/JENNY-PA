"""données et split figé."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ml.models.intent_head.augment import plain

DATA_PATH = Path("data/generated/intents.jsonl")
SEED = 42


def load_rows(path: str | Path = DATA_PATH) -> list[dict]:
    """lit le jsonl."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(ligne) for ligne in lines if ligne.strip()]


def frozen_split(total: int, seed: int = SEED) -> dict[str, list[int]]:
    """même split que le lstm."""
    import torch
    from torch.utils.data import random_split

    train_size = int(0.70 * total)
    val_size = int(0.15 * total)
    test_size = total - train_size - val_size
    gen = torch.Generator().manual_seed(seed)
    tr, va, te = random_split(range(total), [train_size, val_size, test_size], generator=gen)
    return {"train": list(tr.indices), "val": list(va.indices), "test": list(te.indices)}


def labels_of(row: dict) -> list[str]:
    """étiquettes d'une ligne."""
    labs = row.get("intents") or ([row["intent"]] if row.get("intent") else [])
    return list(labs) or ["general"]


def norm_key(text: str) -> str:
    """clé de doublon."""
    return plain(text).replace("'", " ").replace("-", " ").strip()


@dataclass
class Group:
    """textes identiques du train."""

    text: str
    votes: Counter = field(default_factory=Counter)
    # (primaire, secondaire) vus
    pairs: Counter = field(default_factory=Counter)
    n: int = 0
    label: str = ""

    @property
    def conflict(self) -> bool:
        return len(self.votes) > 1

    def tied(self) -> list[str]:
        """étiquettes à égalité."""
        top = max(self.votes.values())
        return sorted(lab for lab, c in self.votes.items() if c == top)

    def label_set(self) -> list[str]:
        """primaire + secondaires d'accord."""
        n = self.votes.get(self.label, 0)
        # au moins une ligne sur deux
        extra = sorted(
            s
            for (p, s), c in self.pairs.items()
            if p == self.label and s != self.label and 2 * c >= n
        )
        return [self.label, *extra]


def group_train(rows: list[dict], train_idx: list[int]) -> list[Group]:
    """dédoublonne le train."""
    groups: dict[str, Group] = {}
    for i in train_idx:
        row = rows[i]
        key = norm_key(row["text"])
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(text=row["text"])
        labs = labels_of(row)
        g.votes[labs[0]] += 1
        for sec in labs[1:]:
            g.pairs[(labs[0], sec)] += 1
        g.n += 1
    return list(groups.values())
