"""Hygiène des dépendances : cœur léger, extras cohérents, outils alignés."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CORE = {canonicalize_name(Requirement(r).name) for r in PYPROJECT["project"]["dependencies"]}
EXTRAS = PYPROJECT["project"]["optional-dependencies"]

# paquets de l'extra [ml]
ML_ONLY = {"mlflow", "datasets", "groq", "rich"}
# imports paresseux et gardés
OPTIONAL = {"fitz", "pdfplumber", "google", "googleapiclient", "opentelemetry"}
# tirés par une dep déclarée
TRANSITIVE = {"starlette": "fastapi", "bcrypt": "passlib"}
# modules maison
LOCAL = {"jenny", "ml", "nanogpt"}


def _third_party_imports(base: Path) -> dict[str, set[str]]:
    """Modules tiers importés, par fichier."""
    found: dict[str, set[str]] = {}
    for path in base.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in sys.stdlib_module_names or name in LOCAL or name == "__future__":
                    continue
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


SRC_IMPORTS = _third_party_imports(ROOT / "src" / "jenny")


def test_src_never_imports_ml_extra() -> None:
    """src/jenny sans mlflow & co."""
    leaks = {m: sorted(f) for m, f in SRC_IMPORTS.items() if m in ML_ONLY}
    assert leaks == {}


def test_src_imports_are_declared() -> None:
    """Chaque import tiers est déclaré."""
    dists = metadata.packages_distributions()
    missing = {}
    for module, files in SRC_IMPORTS.items():
        if module in OPTIONAL:
            continue
        if module in TRANSITIVE:
            assert canonicalize_name(TRANSITIVE[module]) in CORE
            continue
        names = {canonicalize_name(d) for d in dists.get(module, [])}
        if not names & CORE:
            missing[module] = sorted(files)
    assert missing == {}, "à déclarer dans [project].dependencies"


def test_extras_layout() -> None:
    """[ml] et [dev] bien rangés."""
    ml = {canonicalize_name(Requirement(r).name) for r in EXTRAS["ml"]}
    dev = {canonicalize_name(Requirement(r).name) for r in EXTRAS["dev"]}
    assert ml >= ML_ONLY
    assert not (ML_ONLY & CORE)
    # sécurité et fuseaux
    assert {"cryptography", "tzdata"} <= CORE
    assert {"pytest-timeout", "pytest-cov", "aiosqlite"} <= dev


def test_precommit_ruff_matches_pyproject() -> None:
    """pre-commit = ruff du pyproject."""
    ruff = next(Requirement(r) for r in EXTRAS["dev"] if Requirement(r).name == "ruff")
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    m = re.search(r"ruff-pre-commit\s*\n\s*rev:\s*v?([\w.]+)", config)
    assert m, "hook ruff introuvable"
    assert ruff.specifier.contains(Version(m.group(1))), (m.group(1), str(ruff.specifier))


def test_runtime_imports_without_ml_extra() -> None:
    """Toute l'app s'importe sans [ml]."""
    code = """
import importlib, pkgutil, sys
BLOCK = {__BLOCK__}
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError("bloque: " + name)
        return None
sys.meta_path.insert(0, _Block())
import jenny
bad = []
for m in pkgutil.walk_packages(jenny.__path__, "jenny."):
    if m.name.startswith("jenny.scripts"):
        continue
    try:
        importlib.import_module(m.name)
    except Exception as e:
        bad.append(m.name + ": " + repr(e))
for name in ("ml.models.intent.predict", "ml.models.ner.predict", "nanogpt.generate"):
    importlib.import_module(name)
from jenny.api.main import create_app
create_app()
print("BAD", bad)
""".replace("__BLOCK__", ", ".join(repr(m) for m in sorted(ML_ONLY | {"pandas", "pyarrow"})))
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "BAD []" in proc.stdout, proc.stdout[-2000:]
