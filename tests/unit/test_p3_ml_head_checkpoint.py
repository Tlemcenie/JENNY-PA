"""tête servie : checkpoint cohérent, inférence légère."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ml.models.intent.config import INTENT_LABELS
from ml.models.intent_head.predict import DEFAULT_PATH, ENCODER_NAME, FORMAT, load_checkpoint

META = DEFAULT_PATH.parent / "meta.json"
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not DEFAULT_PATH.exists(), reason="checkpoint tête absent")

# inférence sans les libs d'entraînement
SCRIPT = r"""
import importlib.abc
import sys

import numpy as np

BLOQUES = {"sklearn", "scipy", "joblib", "sentence_transformers"}


class Bloque(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in BLOQUES:
            raise ImportError("bloqué : " + name)
        return None


sys.meta_path.insert(0, Bloque())

from ml.models.intent_head.predict import EmbeddingIntentPredictor


class Enc:
    def get_sentence_embedding_dimension(self):
        return 768

    def encode(self, texts, **kw):
        out = []
        for t in texts:
            rng = np.random.default_rng(len(t))
            v = rng.standard_normal(768)
            out.append(v / np.linalg.norm(v))
        return np.asarray(out, dtype=np.float32)


head = EmbeddingIntentPredictor.from_checkpoint(sys.argv[1], encoder=Enc())
res = head.predict_multi("Je voudrais un rdv samedi, vous prenez la CB ?")
assert res["primary_intent"] in head.labels
assert head.has_secondary and head.chars is not None
print("OK", sorted(m for m in sys.modules if m.split(".")[0] in BLOQUES))
"""


class TestCheckpointServi:
    """le npz colle au code."""

    def test_format_et_formes(self) -> None:
        arrays, cfg = load_checkpoint(DEFAULT_PATH)
        assert cfg["format"] == FORMAT and cfg["encoder"] == ENCODER_NAME
        n = len(INTENT_LABELS)
        assert arrays["labels"].tolist() == INTENT_LABELS
        assert arrays["coef"].shape == (n, 768) and arrays["intercept"].shape == (n,)
        # 14 un-contre-tous + multi
        assert arrays["sec_coef"].shape == (n + 1, 768)
        assert arrays["sec_intercept"].shape == (n + 1,)
        v = len(arrays["char_vocab"])
        assert arrays["char_coef"].shape == (n, v) and arrays["sec_char_coef"].shape == (n + 1, v)
        assert all(a.dtype != object for a in arrays.values())

    def test_meta_versionnee_identique(self) -> None:
        _, cfg = load_checkpoint(DEFAULT_PATH)
        meta = json.loads(META.read_text(encoding="utf-8"))
        assert cfg["meta"] == meta
        sec = meta["secondaires"]
        # seuils servis = seuils calés
        assert cfg["multi_threshold"] == sec["t_multi"]
        assert cfg["ovr_threshold"] == sec["t_ovr_fort"]
        assert cfg["second_floor"] == sec["plancher_secondaire"]
        assert round(cfg["temperature"], 4) == meta["temperature"]
        assert meta["char_vocab"] == len(load_checkpoint(DEFAULT_PATH)[0]["char_vocab"])

    def test_choix_sur_val_seule(self) -> None:
        meta = json.loads(META.read_text(encoding="utf-8"))
        assert meta["split"] == {"train": 3542, "val": 759, "test": 760}
        # aucun chiffre test dans la meta
        assert not any("test" in k for k in meta)
        assert (
            meta["secondaires"]["val"]["propre"]["faux"]
            <= meta["secondaires"]["plafond_faux_multi_pct"]
        )

    def test_poids_finis(self) -> None:
        arrays, _ = load_checkpoint(DEFAULT_PATH)
        for k, a in arrays.items():
            if a.dtype.kind == "f":
                assert np.isfinite(a).all(), k


class TestInferenceLegere:
    """ni sklearn, ni scipy, ni joblib."""

    def test_sans_libs_entrainement(self) -> None:
        out = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(ROOT / DEFAULT_PATH)],
            cwd=ROOT,
            env={
                "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", "/tmp"),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert out.returncode == 0, out.stderr[-2000:]
        # logs avant la ligne finale
        assert out.stdout.strip().splitlines()[-1] == "OK []"
