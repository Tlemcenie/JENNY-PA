"""Deps du chemin ML de prod : ml/ et nanogpt/ chargés par src."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests.unit.test_ci_dependencies import CORE, LOCAL, ML_ONLY, OPTIONAL, ROOT

# tirés par une dep déclarée
TRANSITIVE = {"starlette": "fastapi", "bcrypt": "passlib", "scipy": "scikit-learn"}


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """Imports tiers et locaux d'un fichier."""
    third, local = set(), set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in ("ml", "nanogpt"):
                local.add(name)
            elif top not in sys.stdlib_module_names and top not in LOCAL and top != "__future__":
                third.add(top)
    return third, local


def _module_file(name: str) -> Path | None:
    """Fichier d'un module maison."""
    base = ROOT.joinpath(*name.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _runtime_closure() -> dict[str, set[str]]:
    """Modules ml/nanogpt atteints depuis src, avec leurs imports."""
    todo: set[str] = set()
    for path in (ROOT / "src" / "jenny").rglob("*.py"):
        if "scripts" in path.parts:
            continue
        todo |= _imports(path)[1]
    seen: dict[str, set[str]] = {}
    while todo:
        name = todo.pop()
        path = _module_file(name)
        if path is None:
            # from pkg import nom
            path = _module_file(name.rsplit(".", 1)[0]) if "." in name else None
        if path is None or str(path) in seen:
            continue
        third, local = _imports(path)
        seen[str(path)] = third
        todo |= local
        # paquets parents chargés aussi
        parts = name.split(".")
        for i in range(1, len(parts)):
            todo.add(".".join(parts[:i]))
    return seen


CLOSURE = _runtime_closure()


def test_closure_couvre_le_chemin_ml() -> None:
    """Tête, lstm, ner et nanogpt vus."""
    rel = {str(Path(p).relative_to(ROOT)) for p in CLOSURE}
    assert {
        "ml/models/intent_head/predict.py",
        "ml/models/intent_head/features.py",
        "ml/models/intent/predict.py",
        "ml/models/ner/predict.py",
        "nanogpt/generate.py",
    } <= rel
    # entraînement hors chemin
    assert "ml/models/intent_head/train.py" not in rel


def test_ml_runtime_deps_declarees() -> None:
    """Chaque import du chemin ML est déclaré."""
    dists = metadata.packages_distributions()
    missing: dict[str, list[str]] = {}
    for path, mods in CLOSURE.items():
        for module in mods:
            if module in OPTIONAL:
                continue
            if module in TRANSITIVE:
                continue
            names = {canonicalize_name(d) for d in dists.get(module, [])}
            if not names & CORE:
                missing.setdefault(module, []).append(str(Path(path).relative_to(ROOT)))
    assert missing == {}, "à déclarer dans [project].dependencies"


def test_ml_runtime_sans_extra_ml() -> None:
    """Pas de mlflow & co sur le chemin."""
    leaks = {
        str(Path(p).relative_to(ROOT)): sorted(m & ML_ONLY) for p, m in CLOSURE.items() if m & ML_ONLY
    }
    assert leaks == {}


def test_transitives_reelles() -> None:
    """Le parent tire bien la dep."""
    for module, parent in TRANSITIVE.items():
        assert canonicalize_name(parent) in CORE
        requires = {canonicalize_name(Requirement(r).name) for r in metadata.requires(parent) or []}
        dist = metadata.packages_distributions()[module][0]
        assert canonicalize_name(dist) in requires, (module, parent)


def test_tete_intention_deps_explicites() -> None:
    """numpy, joblib, sklearn au cœur."""
    assert {"numpy", "joblib", "scikit-learn"} <= CORE


def test_chemin_ml_importable_sans_extra() -> None:
    """Tout le chemin ML s'importe sans [ml]."""
    mods = sorted(
        ".".join(Path(p).relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
        for p in CLOSURE
    )
    code = f"""
import importlib, sys
BLOCK = {sorted(ML_ONLY | {"pandas", "pyarrow"})!r}
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError("bloque: " + name)
        return None
sys.meta_path.insert(0, _Block())
for name in {mods!r}:
    importlib.import_module(name)
from ml.models.intent_head.predict import EmbeddingIntentPredictor
print("OK", len({mods!r}))
"""
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.startswith("OK"), proc.stdout[-2000:]
