"""Tests d'intégration pour l'endpoint POST /api/v1/ingest/form.

Ces tests vérifient que le webhook de formulaire fonctionne de bout en bout
avec le client HTTP async (sans base de données réelle).

NOTE: ces tests nécessitent une DB de test pour fonctionner complètement.
Pour l'instant on teste seulement la validation du payload.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ingest_form_validation_error(async_client: AsyncClient) -> None:
    """Un payload invalide (message vide) retourne 422."""
    business_id = str(uuid4())
    response = await async_client.post(
        f"/api/v1/ingest/form?business_id={business_id}",
        json={
            "form_id": "test",
            "submitted_at": "2026-03-10T14:00:00Z",
            "message": "",  # Vide → invalide
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_form_missing_required_fields(async_client: AsyncClient) -> None:
    """Un payload sans champs obligatoires retourne 422."""
    business_id = str(uuid4())
    response = await async_client.post(
        f"/api/v1/ingest/form?business_id={business_id}",
        json={
            "full_name": "Marie",
            # Manque form_id, submitted_at, message
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_form_missing_business_id(async_client: AsyncClient) -> None:
    """Sans business_id en query param, retourne 422."""
    response = await async_client.post(
        "/api/v1/ingest/form",
        json={
            "form_id": "test",
            "submitted_at": "2026-03-10T14:00:00Z",
            "message": "Bonjour",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_form_invalid_email(async_client: AsyncClient) -> None:
    """Un email invalide dans le payload retourne 422."""
    business_id = str(uuid4())
    response = await async_client.post(
        f"/api/v1/ingest/form?business_id={business_id}",
        json={
            "form_id": "test",
            "submitted_at": "2026-03-10T14:00:00Z",
            "email": "pas-un-email",
            "message": "Bonjour",
        },
    )
    assert response.status_code == 422
