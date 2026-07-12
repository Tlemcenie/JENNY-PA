# Jenny — AI-Powered Customer Message Platform

> Plateforme backend IA pour la gestion intelligente des messages clients (Instagram, WhatsApp, Messenger, email, formulaires).

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

Remplace `OWNER/REPO` dans l’URL du badge après création du dépôt GitHub.

## Architecture

```
Platform Layer   →  FastAPI API, routes, middlewares
Application      →  Services, workers ARQ, connecteurs
AI / ML          →  Moteur d'agents maison, RAG, LLM providers, NanoGPT
Data             →  PostgreSQL + pgvector, Redis, SQLAlchemy
Infrastructure   →  Docker, Compose, MLflow, observabilité
```

## Stack

| Composant | Technologie |
|---|---|
| API | FastAPI + Pydantic v2 |
| DB | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Cache/Broker | Redis 7 |
| Jobs async | ARQ |
| Agents | Orchestration maison (Python, sans framework) |
| ML Tracking | MLflow |
| Deep Learning | PyTorch |
| Mini LLM | NanoGPT (from scratch) |
| Lint/Format | Ruff |
| Typecheck | mypy |
| Tests | pytest + httpx |
| CI | GitHub Actions (PR + push sur `main`) |

## Démarrage rapide

### Prérequis

- Docker & Docker Compose (suffisant pour tout faire tourner)
- Python **3.12+** (uniquement si tu veux développer en local)
- Make (optionnel mais conseillé)

### Tout lancer en une commande (Docker)

```bash
make demo-up        # build + up + migrate + seed  (API + interface + infra)
```

À la fin tu obtiens **toute la stack**, interface comprise :

| Service           | URL                                  |
| ----------------- | ------------------------------------ |
| **Interface web** | **http://localhost:3000**            |
| API + Swagger     | http://localhost:8000/docs           |
| Health / Ready    | http://localhost:8000/health, /ready |
| Mailhog (UI mail) | http://localhost:8025                |
| MLflow            | http://localhost:5000                |

Compte de démonstration créé automatiquement :

- email : `demo@jenny.ai`
- mot de passe : `Demo!1234`

> **Pour un chat pleinement intelligent** — le provider LLM par défaut est **Groq**
> (rapide, quota gratuit généreux). Récupère une clé sur
> [console.groq.com](https://console.groq.com), mets-la dans `.env`
> (`JENNY_GROQ_API_KEY=gsk_...`), puis `docker compose up -d api`. Sans clé, l'API
> tourne mais le chat retombe sur des réponses génériques. Alternative 100 % locale :
> [Ollama](https://ollama.com) + `JENNY_LLM_PROVIDER=llama` (voir `.env.example`).

Pour tout arrêter (et purger les volumes) :

```bash
make demo-down
```

### Mode développeur (Python local)

```bash
cp .env.example .env
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

# infra (Postgres, Redis, Mailhog, MLflow) en docker
make up

# migrations + seed
make migrate
make seed

# API + Worker
make api          # dans un terminal
make worker       # dans un autre terminal
```

L’API est accessible sur `http://localhost:8000`.
La documentation OpenAPI est sur `http://localhost:8000/docs`.

### Checkpoints ML (tests e2e)

Les tests end-to-end attendent les poids :

- `checkpoints/intent/best_model.pt`
- `checkpoints/ner/best_model.pt`

S’ils sont absents : `python scripts/train_models.py`  
(ces fichiers peuvent être versionnés dans le dépôt pour la CI — voir `.gitignore`.)

### Commandes utiles

```bash
make help          # Voir toutes les commandes disponibles
make demo-up       # Stack complète + migrations + seed démo
make demo-down     # Stop + purge volumes
make api           # Lancer l’API en local
make worker        # Lancer le worker ARQ
make seed          # Insérer les données de démo (idempotent)
make reseed        # Purger puis ré-insérer le seed
make test          # Tests unitaires + intégration
make test-e2e      # Pipelines e2e (auth/chat/rdv/devis/services)
make smoke         # Smoke test contre un serveur live (BASE_URL=...)
make lint          # Ruff lint
make format        # Ruff format + autofix
make format-check  # Vérifier le format sans modifier (CI)
make typecheck     # mypy
make ci            # Même chaîne que la CI GitHub
make up / make down
```

### Tests end-to-end

- `make test-e2e` : pipelines e2e in-process (FastAPI ASGI, sans DB).
- `make smoke` : exécute `scripts/e2e_smoke.py` contre `BASE_URL` (par défaut `http://localhost:8000`). Couvre `/health`, `/ready`, register/login/me sur la base réelle, chat multi-tour, escalade humaine. À utiliser après `make demo-up`.

### Intégrations externes

Les connecteurs sont **réels** (pas de simulation cachée). Pour les activer, renseigner les clés correspondantes dans `.env` :

| Domaine          | Variables clés                                                                  |
| ---------------- | ------------------------------------------------------------------------------- |
| LLM              | `JENNY_LLM_PROVIDER`, `JENNY_GROQ_API_KEY`, `JENNY_OPENAI_API_KEY`, `JENNY_MISTRAL_API_KEY`, `JENNY_LLAMA_BASE_URL` |
| WhatsApp / Insta | `JENNY_WHATSAPP_*`, `JENNY_INSTAGRAM_*`, `JENNY_FACEBOOK_APP_SECRET`            |
| Stripe / PayPal  | `JENNY_STRIPE_*`, `JENNY_PAYPAL_*`                                              |
| Email            | `JENNY_SMTP_*` (Mailhog en local), `JENNY_IMAP_*` pour l'inbound                |
| Twilio (SMS)     | `JENNY_TWILIO_*`                                                                |
| Google Calendar  | `JENNY_GOOGLE_SERVICE_ACCOUNT_JSON`, `JENNY_GOOGLE_CALENDAR_ID`                 |
| Google OAuth     | `JENNY_GOOGLE_OAUTH_CLIENT_ID`, `JENNY_GOOGLE_OAUTH_CLIENT_SECRET`              |

Sans clés, les modules basculent automatiquement en mode "templates" / dégradé (Calendar simulé, LLM templates, etc.) pour garder le backend démarrable et testable.

## Git, PR et CI

- **Workflow** : branches → Pull Requests vers `main` ; la CI exécute lint, format, mypy et pytest (voir `.github/workflows/ci.yml`).
- **Guide contributeur** : [CONTRIBUTING.md](CONTRIBUTING.md).
- **Template de PR** : [`.github/pull_request_template.md`](.github/pull_request_template.md).

### Première mise sur GitHub

```bash
git init
git add .
git commit -m "chore: initial import"
git branch -M main
git remote add origin https://github.com/OWNER/REPO.git
git push -u origin main
```

Puis activer les workflows dans l’onglet **Actions** du dépôt.

## Structure du projet

```
src/jenny/         # Package applicatif principal
├── api/           # FastAPI (routes, deps, middlewares)
├── core/          # Config, logging, exceptions
├── domain/        # Modèles SQLAlchemy + schémas Pydantic
├── services/      # Logique métier
├── db/            # Session, base, repositories
├── workers/       # Tâches async ARQ
├── connectors/    # Connecteurs messagerie (WhatsApp, IG...)
├── agents/        # Orchestration LangGraph
├── rag/           # Retrieval-Augmented Generation
└── llm/           # Abstraction fournisseurs LLM

ml/                # Couche ML / expérimentation
├── training/      # Boucle d'entraînement
├── evaluation/    # Métriques et évaluation
├── inference/     # Prédiction en production
├── features/      # Feature engineering
├── tracking/      # Intégration MLflow
└── registry/      # Model registry

nanogpt/           # Mini LLM from scratch
├── model.py       # Architecture Transformer
├── config.py      # Hyperparamètres
├── train.py       # Entraînement
└── generate.py    # Génération de texte

pipelines/         # Pipelines orchestrés
├── data_pipeline.py
├── training_pipeline.py
└── inference_pipeline.py

data/              # Données (gitignored)
├── raw/
├── interim/
├── processed/
├── labeled/
├── synthetic/
└── prompts/
```

## Endpoints API (aperçu)

| Méthode | Route | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check |
| POST | `/api/v1/messages/` | Créer un message |
| GET | `/api/v1/messages/` | Lister les messages |
| POST | `/api/v1/conversation/chat` | Moteur conversationnel (intent, entités, agents) |

## Roadmap

- [x] Phase 1 — Fondations backend (API, DB, config, Docker)
- [x] Phase 2 — Ingestion / connecteurs (formulaire, email ; autres canaux en cours)
- [x] Phase 3 — RAG (pgvector, embeddings, base de connaissances)
- [x] Phase 4 — Agents (LangGraph, routage multi-intent)
- [x] Phase 5 — ML supervisé (intent / NER PyTorch, checkpoints)
- [ ] Phase 6 — NanoGPT expérimental
- [ ] Phase 7 — Observabilité / durcissement / déploiement cloud

Pour une **réflexion** sur GCP, Airflow, dbt, Databricks (sans engagement) : [docs/DEPLOYMENT_FUTURE.md](docs/DEPLOYMENT_FUTURE.md).

## Licence

MIT
