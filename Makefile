# ──────────────────────────────────────────────
# Jenny — Makefile
# ──────────────────────────────────────────────

# Utilise le venv local si dispo, sinon python3.12 / python3 / python
PYTHON ?= $(shell \
	if [ -x .venv/bin/python ]; then echo .venv/bin/python; \
	elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; \
	elif command -v python3 >/dev/null 2>&1; then command -v python3; \
	else command -v python; fi)

.PHONY: help install dev api worker test test-cov test-e2e smoke test-connectors test-connectors-webhook lint format format-check \
	typecheck ci migrate migrate-new up down logs build clean bootstrap seed reseed \
	demo-up demo-down

help: ## Afficher l'aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ──
install: ## Installer les dépendances Python (mode éditable)
	$(PYTHON) -m pip install -e ".[dev]"

dev: ## Setup complet dev (install + pre-commit)
	$(PYTHON) -m pip install -e ".[dev]"
	pre-commit install || true

bootstrap: ## Premier lancement : .env + docker up + migrate + seed
	@if [ ! -f .env ]; then cp .env.example .env && echo "✓ .env créé depuis .env.example"; fi
	@docker info >/dev/null 2>&1 || (echo "⚠ Docker n'est pas démarré. Lance Docker Desktop puis relance make bootstrap." && exit 1)
	docker compose up -d postgres redis mailhog
	docker compose up -d --build api worker
	@echo "✓ Stack Jenny prête : http://localhost:8000/docs (demo@jenny.ai / Demo!1234)"

# ── Serveurs ──
api: ## Lancer l'API en local (sans Docker)
	PYTHONPATH=src $(PYTHON) -m uvicorn jenny.api.main:app --host 0.0.0.0 --port 8000 --reload

worker: ## Lancer le worker ARQ (sans Docker)
	PYTHONPATH=src $(PYTHON) -m arq jenny.workers.tasks.WorkerSettings

# ── Tests ──
test: ## Lancer la suite de tests
	PYTHONPATH=src:. $(PYTHON) -m pytest tests/ -v --tb=short

test-cov: ## Tests avec couverture HTML
	PYTHONPATH=src:. $(PYTHON) -m pytest tests/ -v --tb=short --cov=jenny --cov-report=html

test-e2e: ## Pipelines e2e in-process (auth/chat/rdv/devis/services)
	PYTHONPATH=src:. $(PYTHON) -m pytest tests/e2e/ -v --tb=short

smoke: ## Smoke test contre un serveur live (BASE_URL=http://localhost:8000)
	PYTHONPATH=src:. $(PYTHON) scripts/e2e_smoke.py

test-connectors: ## Tester la configuration des connecteurs
	PYTHONPATH=src:. $(PYTHON) scripts/test_connectors.py --env-check

test-connectors-webhook: ## Simuler un webhook (ex: make test-connectors-webhook channel=whatsapp)
	PYTHONPATH=src:. $(PYTHON) scripts/test_connectors.py --webhook $(channel)

# ── Qualité de code ──
lint: ## Vérifier le code avec ruff
	$(PYTHON) -m ruff check src/ tests/ ml/ nanogpt/ pipelines/

format: ## Formater le code avec ruff
	$(PYTHON) -m ruff format src/ tests/ ml/ nanogpt/ pipelines/
	$(PYTHON) -m ruff check --fix src/ tests/ ml/ nanogpt/ pipelines/

format-check: ## Vérifier le formatage sans modifier (CI)
	$(PYTHON) -m ruff format --check src/ tests/ ml/ nanogpt/ pipelines/

typecheck: ## Vérifier les types avec mypy
	PYTHONPATH=src $(PYTHON) -m mypy src/jenny/

ci: ## Même séquence que la CI GitHub (lint + format + types + tests)
	$(PYTHON) -m ruff check src/ tests/ ml/ nanogpt/ pipelines/
	$(PYTHON) -m ruff format --check src/ tests/ ml/ nanogpt/ pipelines/
	PYTHONPATH=src $(PYTHON) -m mypy src/jenny/
	PYTHONPATH=src:. $(PYTHON) -m pytest tests/ -q --tb=short

# ── Base de données ──
migrate: ## Appliquer les migrations Alembic
	PYTHONPATH=src $(PYTHON) -m alembic upgrade head

migrate-new: ## Créer une migration (usage: make migrate-new msg="description")
	PYTHONPATH=src $(PYTHON) -m alembic revision --autogenerate -m "$(msg)"

seed: ## Insérer les données de démonstration (idempotent)
	PYTHONPATH=src:. $(PYTHON) -m jenny.scripts.seed_demo

reseed: ## Purger puis ré-insérer les données de démo
	PYTHONPATH=src:. $(PYTHON) -m jenny.scripts.seed_demo --force

# ── Docker ──
up: ## Lancer tous les services (docker compose)
	@docker info >/dev/null 2>&1 || (echo "⚠ Docker n'est pas démarré. Lance Docker Desktop." && exit 1)
	docker compose up -d

down: ## Arrêter tous les services
	docker compose down

logs: ## Voir les logs des services
	docker compose logs -f

build: ## Rebuild les images Docker
	docker compose build

demo-up: ## Stack complète démo : up + migrate + seed (nécessite Docker)
	@docker info >/dev/null 2>&1 || (echo "⚠ Docker n'est pas démarré. Lance Docker Desktop puis relance make demo-up." && exit 1)
	docker compose up -d --build
	docker compose exec -T api alembic upgrade head
	docker compose exec -T api python3 -m jenny.scripts.seed_demo --force
	@echo "\n✓ Stack prête :"
	@echo "  Interface    : http://localhost:3000"
	@echo "  API + Swagger : http://localhost:8000/docs"
	@echo "  Mailhog UI   : http://localhost:8025"
	@echo "  MLflow       : http://localhost:5000"
	@echo "  Compte démo  : demo@jenny.ai / Demo!1234"
	@echo "\n  ⚠ Pour un chat pleinement intelligent : mets ta clé Groq (gratuite)"
	@echo "    dans .env → JENNY_GROQ_API_KEY=gsk_... puis 'docker compose up -d api'"

demo-down: ## Arrêter la stack et nettoyer les volumes
	docker compose down -v

# ── Nettoyage ──
clean: ## Nettoyer les fichiers temporaires
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage dist/ build/
