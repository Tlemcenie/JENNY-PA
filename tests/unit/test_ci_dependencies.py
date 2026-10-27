"""Hygiène des dépendances : cœur léger, extras cohérents, outils alignés.

Le chemin de prod couvre src/jenny ET les modules ml/
que src charge (tête d'intention).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

if TYPE_CHECKING:
    from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CORE = {canonicalize_name(Requirement(r).name) for r in PYPROJECT["project"]["dependencies"]}
EXTRAS = PYPROJECT["project"]["optional-dependencies"]
ML_EXTRA = {canonicalize_name(Requirement(r).name) for r in EXTRAS["ml"]}

# paquets de l'extra [ml], bannis du chemin de prod
ML_ONLY = {"sklearn"}
# imports paresseux et gardés
OPTIONAL = {"fitz", "pdfplumber", "google", "googleapiclient", "opentelemetry"}
# tirés par une dep déclarée
TRANSITIVE = {
    "starlette": "fastapi",
    "bcrypt": "passlib",
    # transform() : entraînement seul
    "scipy": "sentence-transformers",
}
# modules maison
LOCAL = {"jenny", "ml"}
# nom d'import != nom pip
IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "jwt": "pyjwt",
    "yaml": "pyyaml",
    "PIL": "pillow",
}
# modules maison suivis depuis src
FOLLOWED = ("ml",)


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """Imports tiers et maison d'un fichier."""
    third, local = set(), set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # from pkg import sous_module
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in FOLLOWED:
                local.add(name)
            elif top not in sys.stdlib_module_names and top not in LOCAL and top != "__future__":
                third.add(top)
    return third, local


def _third_party_imports(base: Path) -> dict[str, set[str]]:
    """Modules tiers importés, par module."""
    found: dict[str, set[str]] = {}
    for path in base.rglob("*.py"):
        for name in _imports(path)[0]:
            found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


def _module_file(name: str) -> Path | None:
    """Fichier d'un module maison."""
    base = ROOT.joinpath(*name.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _runtime_closure() -> dict[Path, set[str]]:
    """Fichiers ml/ atteints depuis src, avec leurs imports tiers."""
    todo: set[str] = set()
    for path in (ROOT / "src" / "jenny").rglob("*.py"):
        if "scripts" in path.parts:
            continue
        todo |= _imports(path)[1]
    seen: dict[Path, set[str]] = {}
    while todo:
        name = todo.pop()
        # paquets parents chargés aussi
        parts = name.split(".")
        todo |= {".".join(parts[:i]) for i in range(1, len(parts))} - {name}
        path = _module_file(name)
        if path is None or path in seen:
            # nom importé, pas un module
            continue
        third, local = _imports(path)
        seen[path] = third
        todo |= local
    return seen


SRC_IMPORTS = _third_party_imports(ROOT / "src" / "jenny")
CLOSURE = _runtime_closure()
RUNTIME_IMPORTS: dict[str, set[str]] = {m: set(f) for m, f in SRC_IMPORTS.items()}
for _path, _mods in CLOSURE.items():
    for _m in _mods:
        RUNTIME_IMPORTS.setdefault(_m, set()).add(str(_path.relative_to(ROOT)))


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _dist_names(module: str, dists: Mapping[str, list[str]]) -> set[str]:
    """Distributions d'un module, même absent."""
    installed = dists.get(module)
    if installed:
        return {canonicalize_name(d) for d in installed}
    # absent ici (CI sans [ml])
    return {canonicalize_name(IMPORT_TO_DIST.get(module, module))}


def _ml_tree_imports() -> dict[str, set[str]]:
    """Imports tiers de ml/."""
    found: dict[str, set[str]] = {}
    for base in ("ml",):
        for module, files in _third_party_imports(ROOT / base).items():
            found.setdefault(module, set()).update(files)
    return found


def _undeclared(
    imports: Mapping[str, set[str]], declared: set[str], dists: Mapping[str, list[str]]
) -> dict[str, list[str]]:
    """Imports sans dep déclarée."""
    return {
        module: sorted(files)
        for module, files in imports.items()
        if module not in OPTIONAL and not _dist_names(module, dists) & declared
    }


# imports prod hors transitifs
DIRECT_RUNTIME = {m: f for m, f in RUNTIME_IMPORTS.items() if m not in TRANSITIVE}


def test_closure_couvre_le_chemin_ml() -> None:
    """Tête d'intention vue."""
    rel = {_rel(p) for p in CLOSURE}
    assert {
        "ml/models/intent_head/predict.py",
        "ml/models/intent_head/features.py",
        "ml/models/intent_head/labels.py",
    } <= rel
    # entraînement hors chemin
    assert not {p for p in rel if p.endswith("/train.py")}


def test_runtime_never_imports_ml_extra() -> None:
    """Chemin de prod sans mlflow & co."""
    leaks = {m: sorted(f) for m, f in RUNTIME_IMPORTS.items() if m in ML_ONLY}
    assert leaks == {}


def test_runtime_imports_are_declared() -> None:
    """Chaque import tiers de prod est déclaré."""
    missing = _undeclared(DIRECT_RUNTIME, CORE, metadata.packages_distributions())
    assert missing == {}, "à déclarer dans [project].dependencies"


def test_transitives_reelles() -> None:
    """Le parent déclaré tire bien la dep."""
    dists = metadata.packages_distributions()
    for module, parent in TRANSITIVE.items():
        assert canonicalize_name(parent) in CORE, parent
        requires = {canonicalize_name(Requirement(r).name) for r in metadata.requires(parent) or []}
        assert canonicalize_name(dists[module][0]) in requires, (module, parent)


def test_ml_tree_deps_declared() -> None:
    """Entraînement : cœur ou [ml]."""
    missing = _undeclared(_ml_tree_imports(), CORE | ML_EXTRA, metadata.packages_distributions())
    assert missing == {}, "à déclarer dans le cœur ou l'extra [ml]"


def test_deps_vues_sans_rien_installe() -> None:
    """Comme la CI sans [ml]."""
    imports = _ml_tree_imports()
    # sklearn vu quand même
    assert set(imports) >= ML_ONLY
    assert _undeclared(imports, CORE | ML_EXTRA, {}) == {}
    assert _undeclared(DIRECT_RUNTIME, CORE, {}) == {}


def test_dep_absente_reste_signalee() -> None:
    """Absent et non déclaré : signalé."""
    imports = {"pandas": {"ml/x.py"}, "sklearn": {"ml/y.py"}, "fitz": {"ml/z.py"}}
    assert _undeclared(imports, CORE | ML_EXTRA, {}) == {"pandas": ["ml/x.py"]}
    # sklearn hors cœur
    assert set(_undeclared(imports, CORE, {})) == {"pandas", "sklearn"}


def test_noms_pip_connus_exacts() -> None:
    """Table import -> pip juste."""
    dists = metadata.packages_distributions()
    for module, dist in IMPORT_TO_DIST.items():
        if module in dists:
            assert canonicalize_name(dist) in _dist_names(module, dists), module


def test_extras_layout() -> None:
    """[ml] et [dev] bien rangés."""
    dev = {canonicalize_name(Requirement(r).name) for r in EXTRAS["dev"]}
    # entraînement hors cœur
    assert "scikit-learn" not in CORE
    # entraînement de la tête
    assert {"scikit-learn", "scipy"} <= ML_EXTRA
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
    """App + chemin ML s'importent sans [ml]."""
    mods = sorted(
        ".".join(p.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
        for p in CLOSURE
    )
    code = f"""
import importlib, pkgutil, sys
BLOCK = {sorted(ML_ONLY | {"pandas", "pyarrow"})!r}
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
for name in {mods!r}:
    try:
        importlib.import_module(name)
    except Exception as e:
        bad.append(name + ": " + repr(e))
from jenny.api.main import create_app
create_app()
print("BAD", bad)
"""
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
