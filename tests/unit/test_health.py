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
    assert response.status_code == 200
    data = response.json()
    # "ready" si DB+Redis dispo, "degraded" sinon (normal en local sans Docker)
    assert data["status"] in ("ready", "degraded")
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
    assert "ml_models" in data["checks"]
    assert data["env"] in ("dev", "test")  # dev en prod local, test en CI
