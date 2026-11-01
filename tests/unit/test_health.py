"""Tests pour les routes de santé."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient) -> None:
    """GET /health retourne un statut healthy."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "jenny-api"


@pytest.mark.asyncio
async def test_readiness_check(async_client: AsyncClient) -> None:
    """GET /ready retourne les infos de readiness."""
    response = await async_client.get("/ready")
    # 200 si prêt, 503 si une dépendance critique (DB/Redis) est indisponible
    # (probe de readiness Cloud Run/K8s). En CI sans DB/Redis joignables → 503.
    assert response.status_code in (200, 503)
    data = response.json()
    assert data["status"] in ("ready", "degraded")
    # Le code HTTP doit être cohérent avec l'état : 200 ⟺ ready, 503 ⟺ degraded.
    assert (response.status_code == 200) == (data["status"] == "ready")
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
    assert "ml_models" in data["checks"]
    assert data["env"] in ("dev", "test")  # dev en prod local, test en CI


# ── la sonde ML regarde le modèle réellement servi ──

def test_ml_check_ok_quand_le_modele_existe(tmp_path, monkeypatch) -> None:
    from jenny.api.routes import health

    f = tmp_path / "head.npz"
    f.write_bytes(b"x")
    monkeypatch.setattr(health, "get_settings", lambda: type("S", (), {
        "enable_ml_models": True, "intent_head_path": str(f)})())
    assert health._check_ml_models() == {"status": "ok", "intent_model": "loaded"}


def test_ml_check_warning_quand_absent(tmp_path, monkeypatch) -> None:
    from jenny.api.routes import health

    monkeypatch.setattr(health, "get_settings", lambda: type("S", (), {
        "enable_ml_models": True, "intent_head_path": str(tmp_path / "absent.npz")})())
    assert health._check_ml_models()["status"] == "warning"


def test_ml_check_skip_si_desactive(monkeypatch) -> None:
    from jenny.api.routes import health

    monkeypatch.setattr(health, "get_settings", lambda: type("S", (), {
        "enable_ml_models": False, "intent_head_path": "peu-importe"})())
    assert health._check_ml_models()["status"] == "skip"
