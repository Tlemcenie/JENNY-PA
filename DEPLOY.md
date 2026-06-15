# Déploiement de Jenny sur Google Cloud Platform (Cloud Run)

Guide pratique pour mettre Jenny en ligne : **API** (FastAPI) + **frontend** (Next.js)
sur **Cloud Run**, **Postgres + pgvector** sur **Cloud SQL**, **Redis** sur **Memorystore**,
et un **LLM hébergé** (Ollama n'existe pas sur Cloud Run).

> Conçu pour un premier déploiement « ça marche, on affinera ». Les points à durcir
> ensuite sont signalés par ⚠️.

## 0. Architecture cible

```
                 ┌─────────────────────┐
  Internet  ───► │ Cloud Run: frontend │  (Next.js standalone, port 8080)
                 └─────────┬───────────┘
                           │  NEXT_PUBLIC_API_URL
                           ▼
                 ┌─────────────────────┐     ┌──────────────────────┐
                 │ Cloud Run: api      │────►│ Cloud SQL (Postgres) │ + pgvector
                 │ (FastAPI, port 8000)│     └──────────────────────┘
                 └─────────┬───────────┘     ┌──────────────────────┐
                           └────────────────►│ Memorystore (Redis)  │
                                             └──────────────────────┘
  Cloud Run Job: worker (cron ARQ — rappels, avis, relances)
  Cloud Run Job: migrate (alembic upgrade head, lancé à chaque release)
```

Le moteur d'intention/NER (PyTorch, CPU) tourne **dans le conteneur API** — pas besoin de GPU.

## 1. Prérequis

```bash
export PROJECT_ID=mon-projet
export REGION=europe-west1
export REPO=jenny
gcloud config set project $PROJECT_ID

gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com redis.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com vpcaccess.googleapis.com

gcloud artifacts repositories create $REPO \
  --repository-format=docker --location=$REGION
```

## 2. Cloud SQL (Postgres + pgvector)

```bash
gcloud sql instances create jenny-pg \
  --database-version=POSTGRES_16 --cpu=1 --memory=4GB --region=$REGION

gcloud sql databases create jenny --instance=jenny-pg
gcloud sql users set-password postgres --instance=jenny-pg --password='UN_MDP_FORT'

# Active pgvector (Cloud SQL le fournit) :
gcloud sql connect jenny-pg --user=postgres --database=jenny
#   puis dans psql :  CREATE EXTENSION IF NOT EXISTS vector;
```

Note le **nom de connexion** : `PROJECT_ID:REGION:jenny-pg`.
URL applicative (via le proxy unix de Cloud Run) :
`postgresql+asyncpg://postgres:UN_MDP_FORT@/jenny?host=/cloudsql/PROJECT_ID:REGION:jenny-pg`

## 3. Memorystore (Redis)

```bash
gcloud redis instances create jenny-redis --size=1 --region=$REGION --redis-version=redis_7_0
gcloud redis instances describe jenny-redis --region=$REGION --format='value(host)'   # → REDIS_IP
```
Memorystore est sur le VPC : Cloud Run a besoin d'un **connecteur VPC** pour l'atteindre.
```bash
gcloud compute networks vpc-access connectors create jenny-conn \
  --region=$REGION --range=10.8.0.0/28
```
⚠️ Sans Redis, l'app **dégrade proprement** (état conversationnel en mémoire, rate-limit
local) — OK pour 1 instance, indispensable dès qu'on scale > 1.

## 4. Secrets

```bash
printf 'un-secret-jwt-long-et-aleatoire' | gcloud secrets create JENNY_JWT_SECRET --data-file=-
printf 'gsk_xxx'                          | gcloud secrets create JENNY_GROQ_API_KEY --data-file=-
printf 'sk_live_xxx'                      | gcloud secrets create JENNY_STRIPE_SECRET_KEY --data-file=-
# … idem pour les tokens WhatsApp/Insta quand vous les aurez.
```

## 5. Build & push des images

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=$REGION,_REPO=$REPO,_API_URL=https://REMPLACER-APRES-1ER-DEPLOY.run.app
```
(Au 1er passage, mettez une URL bidon ; rebuildez le frontend une fois l'URL API connue — voir §8.)

## 6. Migrations (Cloud Run Job)

⚠️ Les migrations **ne doivent pas** tourner à chaque démarrage d'instance (course entre
réplicas). L'`entrypoint` le fait en dev ; en prod, lancez-les via un Job dédié et mettez
`RUN_MIGRATIONS=0` / `JENNY_AUTO_SEED=0` sur le service API.

```bash
IMG=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest
gcloud run jobs create jenny-migrate --image=$IMG --region=$REGION \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --set-env-vars=JENNY_DATABASE_URL='postgresql+asyncpg://postgres:UN_MDP_FORT@/jenny?host=/cloudsql/'$PROJECT_ID:$REGION:jenny-pg \
  --command=alembic --args=upgrade,head
gcloud run jobs execute jenny-migrate --region=$REGION --wait
# Créer le super-admin (une fois) : même job avec --command=python --args=-m,jenny.scripts.create_admin
```

## 7. Déployer l'API

```bash
DBURL='postgresql+asyncpg://postgres:UN_MDP_FORT@/jenny?host=/cloudsql/'$PROJECT_ID:$REGION:jenny-pg
gcloud run deploy jenny-api \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest \
  --region=$REGION --port=8000 --allow-unauthenticated \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --vpc-connector=jenny-conn \
  --set-env-vars=JENNY_ENV=prod,JENNY_REQUIRE_AUTH=true,RUN_MIGRATIONS=0,JENNY_AUTO_SEED=0 \
  --set-env-vars=JENNY_DATABASE_URL="$DBURL" \
  --set-env-vars=JENNY_REDIS_URL=redis://REDIS_IP:6379/0 \
  --set-env-vars=JENNY_LLM_PROVIDER=groq,JENNY_LLM_MODEL=llama-3.3-70b-versatile \
  --set-secrets=JENNY_JWT_SECRET=JENNY_JWT_SECRET:latest,JENNY_GROQ_API_KEY=JENNY_GROQ_API_KEY:latest,JENNY_STRIPE_SECRET_KEY=JENNY_STRIPE_SECRET_KEY:latest \
  --cpu=2 --memory=4Gi --min-instances=0 --max-instances=4 --timeout=120
```
- `--port=8000` : le conteneur API écoute sur 8000 (cf. `docker/api.Dockerfile`).
- `--memory=4Gi` : PyTorch + modèles. ⚠️ L'image est lourde (torch) → cold start lent ;
  pour la réduire, installez torch CPU (`--index-url https://download.pytorch.org/whl/cpu`)
  et retirez `mlflow`/`datasets` (uniquement utiles à l'entraînement).

## 8. Déployer le frontend

Récupérez l'URL de l'API (`gcloud run services describe jenny-api --region=$REGION --format='value(status.url)'`),
**rebuildez le frontend** avec cette URL (`_API_URL`), puis :
```bash
gcloud run deploy jenny-frontend \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/frontend:latest \
  --region=$REGION --port=8080 --allow-unauthenticated \
  --cpu=1 --memory=512Mi --min-instances=0 --max-instances=4
```
Pensez à autoriser l'origine du frontend dans la config CORS de l'API si nécessaire.

## 9. Worker (cron : rappels, avis, relances)

```bash
gcloud run jobs create jenny-worker \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/worker:latest --region=$REGION \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --vpc-connector=jenny-conn \
  --set-env-vars=JENNY_DATABASE_URL="$DBURL",JENNY_REDIS_URL=redis://REDIS_IP:6379/0
# Déclenchez-le chaque minute via Cloud Scheduler :
gcloud scheduler jobs create http jenny-worker-tick --location=$REGION --schedule="* * * * *" \
  --uri="https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/jenny-worker:run" \
  --oauth-service-account-email=SA@$PROJECT_ID.iam.gserviceaccount.com
```

## 10. Ce qui reste à faire / limites connues

- **LLM** : sur GCP on passe par un fournisseur hébergé (Groq/OpenAI/Mistral) via
  `JENNY_LLM_PROVIDER` + clé. Pour garder Ollama, il faut une VM GPU séparée (hors Cloud Run).
- **Messagerie sortante** (WhatsApp/Insta) : le code d'envoi existe ; renseignez les tokens
  Meta pour l'activer (sinon les relances restent des notifications internes).
- **Image API lourde** (torch) : voir §7 pour la réduire.
- Variables d'environnement complètes : voir [`.env.example`](.env.example).
