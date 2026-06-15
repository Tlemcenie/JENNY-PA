"""Configuration globale des tests pytest.

Fournit les fixtures partagées entre tous les tests :
- Client HTTP async pour les tests API
- Session DB de test (SQLite en mémoire, sans Postgres)
- Settings de test

NOTE : les variables d'env JENNY_DATABASE_URL et JENNY_REDIS_URL sont
définies ici AVANT tout import du package jenny, car SQLAlchemy crée
l'engine au niveau module dès que `jenny.db.session` est importé.
"""

import os

# Forcer un environnement de test hermétique, indépendant du `.env` de dev.
# NOTE : os.environ est prioritaire sur le fichier `.env` chargé par
# pydantic-settings, donc ces valeurs neutralisent les réglages locaux
# (Postgres, Ollama, auth requise…) qui ne doivent pas fuiter dans les tests.
os.environ.setdefault("JENNY_DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("JENNY_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JENNY_ENV", "test")
os.environ.setdefault("JENNY_SKIP_META_SIGNATURE", "true")
# Neutralise le business par défaut éventuellement défini dans le .env local :
# sans ça, les webhooks (WhatsApp/IG) routeraient les messages de test vers ce
# business et exécuteraient l'ingestion (au lieu de l'ignorer proprement).
os.environ.setdefault("JENNY_DEFAULT_BUSINESS_ID", "")
# Pas d'auth requise : les tests exercent la logique métier, pas le JWT.
os.environ.setdefault("JENNY_REQUIRE_AUTH", "false")
# Pas de LLM réseau : provider sans clé => fallback templates déterministe.
os.environ.setdefault("JENNY_LLM_PROVIDER", "groq")
# Intentions par règles (déterministes) dans les tests : on ne dépend pas
# d'un checkpoint ML entraîné (absent en CI, susceptible de dériver). Le
# chemin ML reste testé directement via tests/.../TestMLModels.
os.environ.setdefault("JENNY_ENABLE_ML_MODELS", "false")

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from jenny.api.main import create_app
from jenny.core.config import Settings


@pytest.fixture(autouse=True)
def _skip_meta_signature(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("JENNY_SKIP_META_SIGNATURE", "true")


@pytest.fixture
def test_settings() -> Settings:
    """Settings configurés pour les tests."""
    return Settings(
        env="test",
        debug=True,
        log_level="DEBUG",
        database_url="sqlite+aiosqlite:///test.db",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Client HTTP async pour tester les routes FastAPI."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
