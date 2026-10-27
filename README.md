# Jenny — AI-Powered Customer Message Platform

> Plateforme backend IA pour la gestion intelligente des messages clients (Instagram, WhatsApp, Messenger, email, formulaires).

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

Remplace `OWNER/REPO` dans l’URL du badge après création du dépôt GitHub.

## Architecture

```
Platform Layer   →  FastAPI API, routes, middlewares
Application      →  Services, workers ARQ, connecteurs
AI / ML          →  Moteur d'agents maison, RAG hybride, tête d'intention mpnet, LLM Groq
Data             →  PostgreSQL + pgvector, Redis, SQLAlchemy
Infrastructure   →  Docker, Compose, observabilité
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
| Intention | Tête logistique sur mpnet figé (sentence-transformers) |
| LLM | Groq (GPT-OSS 120B), repli OpenAI optionnel |
| Lint/Format | Ruff |
| Typecheck | mypy |
| Tests | pytest + httpx |
| CI | GitHub Actions (PR + push sur `main` / `integration/**`) |

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

Compte de démonstration créé automatiquement :

- email : `demo@jenny.ai`
- mot de passe : `Demo!1234`

> **Pour un chat pleinement intelligent** — le provider LLM par défaut est **Groq**
> (rapide, quota gratuit généreux). Récupère une clé sur
> [console.groq.com](https://console.groq.com), mets-la dans `.env`
> (`JENNY_GROQ_API_KEY=gsk_...`), puis `docker compose up -d api`. Sans clé, l'API
> tourne mais le chat retombe sur des réponses génériques.

Pour tout arrêter (et purger les volumes) :

```bash
make demo-down
```

## Configuration : clés &amp; secrets (`.env`)

> **Important pour qui clone le dépôt.** Les vrais secrets ne sont **jamais versionnés** :
> le fichier `.env` (à la racine) est listé dans le [`.gitignore`](.gitignore) et
> **ne part donc pas sur GitHub**. Tu le crées en copiant le modèle :
> `cp .env.example .env`, puis tu y mets tes propres clés. Le dépôt public ne
> contient que `.env.example` (des placeholders).

Deux clés externes rendent Jenny pleinement fonctionnelle. **Aucune n'est
obligatoire pour démarrer** (l'app tourne sans, en mode dégradé) :

| Clé (`.env`) | À quoi elle sert | Obligatoire ? | Où l'obtenir |
|---|---|---|---|
| `JENNY_GROQ_API_KEY` (`gsk_…`) | **Cerveau du chat** : c'est le LLM qui rédige les réponses de Jenny (provider par défaut). Sans elle, l'API répond avec des textes génériques. | Recommandée (chat intelligent) | [console.groq.com](https://console.groq.com) — **gratuit**, quota généreux |
| `JENNY_SMTP_PASSWORD` (`re_…`) | **Envoi d'emails** via [Resend](https://resend.com) : codes de vérification de compte, réinitialisation de mot de passe, notifications, PDF de devis, réponses email aux clients. | Optionnelle | [resend.com](https://resend.com) — offre gratuite. En **dev**, laisse **Mailhog** (aucune clé, les mails s'affichent sur http://localhost:8025) |

En clair : **Groq = ce que Jenny dit**, **Resend = les emails qu'elle envoie**. En
local tu peux tout tester sans Resend (Mailhog capture les mails). Détails de
chaque variable dans `.env.example`.

### Mode développeur (Python local)

```bash
cp .env.example .env
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

# infra (Postgres, Redis, Mailhog) en docker
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

### Modèle ML

Un seul modèle maison : la **tête d'intention** (`checkpoints/intent_head/head.npz`,
~1 Mo). C'est une régression logistique posée sur l'encodeur figé
`paraphrase-multilingual-mpnet-base-v2`, le même que celui du RAG (un seul
mpnet en mémoire). Sur le test figé : **91,4 %** de bonnes réponses, **89,3 %**
sur des messages écrits façon SMS. Mesure : `python scripts/eval_ml_models.py`,
réentraînement : `python -m ml.models.intent_head.train` (extra `[ml]`).

Les prestations, dates, heures, noms et téléphones sont extraits sans modèle :
règles françaises (`engine/datetime_fr.py`) et repérage tolérant du catalogue
du salon (`engine/catalog_match.py`).

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
make test-services # Tests sur vrais Postgres/Redis (TEST_PG_URL=…)
make test-migrations MIG_PG=postgresql://jenny:jenny_secret@localhost:5432  # base jetable
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

### Environnement de test (hermétique)

`tests/conftest.py` isole chaque run, en local comme en CI :

- **pas de `.env`**, variables `JENNY_*` héritées purgées, base SQLite propre au process
  (clés étrangères actives, comme Postgres), Redis sur un port mort → état en mémoire ;
- **réseau sortant coupé toute la session** (connect, DNS, UDP, httpx) : seul le local
  ouvert par le test lui-même passe, plus les services déclarés dans
  `JENNY_TEST_POSTGRES_URL` / `JENNY_TEST_REDIS_URL`. Le Postgres/Redis de dev
  ne sont **jamais** joints. Un accès tenté fait échouer le test (et le run, même à la
  collecte) ; voulu → fixture `blocked_network` / `blocked_llm_calls` ou marqueur
  `@pytest.mark.allow_network` ;
- Hugging Face hors ligne (`HF_HUB_OFFLINE=1`) : mpnet doit être dans le cache local ;
- RAG : un `HashEmbedder` léger est posé **dans le vrai cache** de `get_default_embedder`
  (la fonction de prod n'est jamais remplacée) ; marqueur `@pytest.mark.real_embedder`
  pour le vrai mpnet ;
- timeout 120 s par test (pytest-timeout, sinon secours SIGALRM du conftest).

Marqueur `services` : tests sur vrais Postgres/Redis (`make test-services`), dont la
**dérive modèles ↔ migrations** (`tests/e2e/test_p3_ci_schema_drift.py`) : un modèle
modifié sans révision Alembic fait échouer la CI.

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

- **Workflow** : branches → Pull Requests vers `main` ; la CI (`.github/workflows/ci.yml`) exécute :
  ruff ; migrations sur une base Postgres **vierge** (upgrade, aller-retour, `alembic check`
  informatif tant que la dérive connue n'est pas résorbée) ; pytest réseau coupé avec les
  vrais Postgres/Redis ; TypeScript + build Next ; sur `main`/`integration/**`, build des
  images Docker (API vérifiée **sans réseau**). Format, mypy et ESLint restent informatifs.
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

ml/                # Tête d'intention (entraînement + inférence)
└── models/intent_head/

data/generated/    # Jeu d'intentions (entraînement de la tête)
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
