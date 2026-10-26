"""Images et CI cohérentes avec le code (sans lancer Docker)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jenny.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
API_PROD = (ROOT / "docker" / "api.prod.Dockerfile").read_text(encoding="utf-8")
API_DEV = (ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
FRONT = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")


def _yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _arg(dockerfile: str, name: str) -> str | None:
    """Valeur par défaut d'un ARG."""
    m = re.search(rf"^ARG {name}=(\S*)", dockerfile, re.M)
    return m.group(1) if m else None


def test_mpnet_dans_les_images_api() -> None:
    """Même modèle que les Settings."""
    model = Settings.model_fields["embeddings_model"].default
    from ml.models.intent_head.predict import ENCODER_NAME

    assert model == ENCODER_NAME
    for dockerfile in (API_PROD, API_DEV):
        assert _arg(dockerfile, "EMBED_MODEL") == model
        assert "SentenceTransformer as S; S('${EMBED_MODEL}'" in dockerfile


def test_api_prod_hors_ligne() -> None:
    """Runtime : cache HF copié, jamais de téléchargement."""
    runtime = API_PROD.split("AS runtime", 1)[1]
    assert "HF_HUB_OFFLINE=1" in runtime
    assert "TRANSFORMERS_OFFLINE=1" in runtime
    assert "HF_HOME=/opt/hf" in runtime
    assert "COPY --from=builder --chown=app:app /opt/hf /opt/hf" in runtime
    # vérif hors ligne au build
    builder = API_PROD.split("AS runtime", 1)[0]
    assert "HF_HUB_OFFLINE=1 python" in builder and "local_files_only=True" in builder


def test_api_prod_embarque_les_scripts_du_job() -> None:
    """reindex_kb.py dispo dans l'image."""
    assert "COPY scripts ./scripts" in API_PROD
    assert (ROOT / "scripts" / "reindex_kb.py").exists()
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert "scripts/" not in ignored and "checkpoints/" not in ignored


def test_front_build_args() -> None:
    """Chaque NEXT_PUBLIC_* lu passe au build."""
    used: set[str] = set()
    for path in (ROOT / "frontend" / "src").rglob("*.ts*"):
        used |= set(re.findall(r"process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)", path.read_text()))
    assert {"NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SITE_URL"} <= used
    for name in used:
        assert _arg(FRONT, name) is not None, name
        assert f"{name}=${name}" in FRONT, name
    steps = _yaml(ROOT / "cloudbuild.yaml")["steps"]
    front = next(s for s in steps if s["id"] == "build-frontend")["args"]
    passed = {a.split("=", 1)[0] for a in front if a.startswith("NEXT_PUBLIC_")}
    assert passed == used


def _steps(job: str) -> dict[str, dict]:
    jobs = _yaml(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]
    return {s.get("name", ""): s for s in jobs[job]["steps"]}


def test_ci_pytest_voit_les_services() -> None:
    """CI : Postgres/Redis passés aux tests."""
    steps = _steps("tests")
    env = steps["Pytest + couverture"]["env"]
    assert env["JENNY_TEST_POSTGRES_URL"] and env["JENNY_TEST_REDIS_URL"]
    assert env["HF_HUB_OFFLINE"] == "1"
    # migrations avant les tests
    names = list(steps)
    assert names.index("Alembic upgrade head (base vierge)") < names.index("Pytest + couverture")


def test_alembic_check_bloquant_si_derive_nulle() -> None:
    """Plus de dérive : check bloquant."""
    from tests.e2e.test_p3_ci_schema_drift import KNOWN_DRIFT

    check = next(s for n, s in _steps("tests").items() if n.startswith("Alembic check"))
    assert check["run"].strip() == "alembic check"
    if not KNOWN_DRIFT:
        assert not check.get("continue-on-error"), "rendre alembic check bloquant"
