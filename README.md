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

## Configuration : clés &amp; secrets (`.env`)

> **Important pour qui clone le dépôt.** Les vrais secrets ne sont **jamais versionnés** :
> le fichier `.env` (à la racine) est listé dans le [`.gitignore`](.gitignore) et
> **ne part donc pas sur GitHub**. Tu le crées en copiant le modèle :
> `cp .env.example .env`, puis tu y mets tes propres clés. Le dépôt public ne
> contient que `.env.example` (des placeholders) et `configs/*.env` (valeurs de
> démo, sans secret).

Deux clés externes rendent Jenny pleinement fonctionnelle. **Aucune n'est
obligatoire pour démarrer** (l'app tourne sans, en mode dégradé) :

| Clé (`.env`) | À quoi elle sert | Obligatoire ? | Où l'obtenir |
|---|---|---|---|
| `JENNY_GROQ_API_KEY` (`gsk_…`) | **Cerveau du chat** : c'est le LLM qui rédige les réponses de Jenny (provider par défaut). Sans elle, l'API répond avec des textes génériques. | Recommandée (chat intelligent) | [console.groq.com](https://console.groq.com) — **gratuit**, quota généreux |
| `JENNY_SMTP_PASSWORD` (`re_…`) | **Envoi d'emails** via [Resend](https://resend.com) : codes de vérification de compte, réinitialisation de mot de passe, notifications, PDF de devis, réponses email aux clients. | Optionnelle | [resend.com](https://resend.com) — offre gratuite. En **dev**, laisse **Mailhog** (aucune clé, les mails s'affichent sur http://localhost:8025) |

En clair : **Groq = ce que Jenny dit**, **Resend = les emails qu'elle envoie**. En
local tu peux tout tester sans Resend (Mailhog capture les mails) et, si tu veux
un chat 100 % local sans clé, remplacer Groq par [Ollama](https://ollama.com)
(`JENNY_LLM_PROVIDER=llama`). Détails de chaque variable dans `.env.example`.

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

### Modèles ML — ce qui est dans le dépôt (et ce qui ne l'est pas)

Jenny embarque **trois modèles maison** entraînés from scratch. Tous ne sont pas
versionnés de la même façon (voir la règle `*.pt` dans le [`.gitignore`](.gitignore)) :

| Modèle | Rôle | Taille | Versionné ? |
|---|---|---|---|
| **Intention** (`checkpoints/intent/best_model.pt`) | Classe le message client (RDV, prix, réclamation…) | ~10 Mo | ✅ **Oui** — nécessaire aux tests e2e / à la CI |
| **Compréhension / NER** (`checkpoints/ner/best_model.pt`) | Extrait les entités (prestation, date, heure, nom, téléphone) | ~8 Mo | ✅ **Oui** — idem |
| **NanoGPT** (`checkpoints/nanogpt/best_model.pt`) | Mini-LLM « fait maison » (vitrine pédagogique de la page Lab) | **~200 Mo** | ❌ **Non** (seul le `tokenizer.json` l'est) |

**Pourquoi NanoGPT est exclu du git.** Le poids fait **~200 Mo**, soit **au-dessus de
la limite de 100 Mo par fichier de GitHub** (et bien au-delà de la limite conseillée
de 50 Mo). L'embarquer alourdirait chaque clone pour un modèle qui n'est qu'une
**démonstration** (« regardez, on a entraîné notre propre LLM ») — il n'entre jamais
dans le chemin de production, où c'est **Groq/Ollama** qui répond. Conséquence sur un
clone : l'onglet « modèle maison » de la page Lab reste vide, **sans aucun impact** sur
le reste de l'application. Pour le régénérer localement : `python -m nanogpt.train`
(voir [`nanogpt/RUNBOOK.md`](nanogpt/RUNBOOK.md)).

Les deux modèles ML « utiles » (intention + NER) sont, eux, **volontairement versionnés**
(~18 Mo au total) pour qu'un clone fonctionne immédiatement et que la CI puisse les
tester. S'ils manquaient : `python scripts/train_models.py`.

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




## Licence

MIT
