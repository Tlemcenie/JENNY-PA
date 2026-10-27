# Déploiement de Jenny sur Google Cloud Platform (Cloud Run)

Guide pratique pour mettre Jenny en ligne : **API** (FastAPI) + **frontend** (Next.js)
sur **Cloud Run**, **Postgres + pgvector** sur **Cloud SQL**, **Redis** sur **Memorystore**,
et un **LLM hébergé** (Groq).

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

Le moteur d'intention (tête mpnet, PyTorch CPU) et le RAG tournent **dans le conteneur API** —
pas besoin de GPU. Le modèle `paraphrase-multilingual-mpnet-base-v2` (~1,1 Go) est
**téléchargé au build** de l'image et lu **hors ligne** (`HF_HUB_OFFLINE=1`) : aucune
instance ne va le chercher sur Hugging Face au démarrage.

## 1. Prérequis

```bash
export PROJECT_ID=mon-projet
export REGION=europe-west9   # Paris → données hébergées en France (RGPD)
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
Les migrations créent aussi `btree_gist` (anti double réservation) et `unaccent`
(recherche plein texte) : l'utilisateur `postgres` de Cloud SQL a le droit de le faire.
Budget de connexions (2 pools par API) : voir [`docs/db_pool.md`](docs/db_pool.md).

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

> **🔴 Mode démo sans Redis — contrainte mono-instance.** L'état conversationnel
> (suivi multi-tours du chat) vit alors en mémoire du process. Il **faut** donc
> forcer **un seul worker ET une seule instance**, sinon deux tours d'une même
> conversation peuvent tomber sur des process différents et Jenny « perd le fil » :
> - API Cloud Run : `--max-instances=1` **et** `WEB_CONCURRENCY=1`
>   (l'entrypoint `docker/entrypoint.prod.sh` force déjà 1 worker uvicorn quand
>   `JENNY_REDIS_URL` est vide — garder les deux cohérents).
> - Dès qu'on rebranche Redis (Memorystore), on peut relever `max-instances` et
>   `WEB_CONCURRENCY` : l'état devient partagé et le suivi survit au scale-out.

## 4. Secrets et variables de prod

Avec `JENNY_ENV=prod`, l'API **refuse de démarrer** si un secret vital manque
(`check_prod_secrets` dans `src/jenny/core/config.py`). Les webhooks, eux, restent
**fermés** tant que leur secret n'est pas posé (jamais ouverts « par défaut ») :

| Variable | Rôle | Si absente |
| --- | --- | --- |
| `JENNY_ENV=prod` | active les garde-fous (auth forcée, HMAC Meta obligatoire) | mode dev : à proscrire |
| `JENNY_JWT_SECRET` | signe les sessions | **démarrage refusé** (vide, `change-me-in-production` ou `CHANGE_ME…`) |
| `JENNY_MASTER_KEY` | clé **Fernet** qui chiffre les identifiants de canal en base | **démarrage refusé** (absente ou pas une clé Fernet) |
| `JENNY_DATABASE_URL` | Cloud SQL (§2) | l'API ne joint pas la base |
| `JENNY_FACEBOOK_APP_SECRET` | signature HMAC des webhooks WhatsApp / Instagram | webhooks Meta en **401** |
| `JENNY_STRIPE_WEBHOOK_SECRET` | signature des webhooks Stripe (§11.5) | webhook Stripe en **503** |
| `JENNY_EMAIL_INBOUND_SECRET` | en-tête `X-Jenny-Inbound-Secret` (SendGrid/Mailgun) | inbound email en **503** |
| `JENNY_SNAPCHAT_WEBHOOK_SECRET` | en-tête `X-Jenny-Webhook-Secret` | webhook Snapchat en **503** |
| `JENNY_PAYPAL_WEBHOOK_ID` + `JENNY_PAYPAL_CLIENT_ID/SECRET` | vérification PayPal | webhook PayPal en **503** |

À poser aussi : `JENNY_GROQ_API_KEY` (sinon réponses « templates »),
`JENNY_PUBLIC_API_BASE_URL` (URL de webhook affichée aux salons), `JENNY_APP_BASE_URL`
et `JENNY_CORS_ORIGINS` = **URL du frontend** (le défaut `*` est trop large en prod).

```bash
printf 'un-secret-jwt-long-et-aleatoire' | gcloud secrets create JENNY_JWT_SECRET --data-file=-
printf 'gsk_xxx'                          | gcloud secrets create JENNY_GROQ_API_KEY --data-file=-
printf 'sk_live_xxx'                      | gcloud secrets create JENNY_STRIPE_SECRET_KEY --data-file=-

# Clé de chiffrement au repos des identifiants de canal (Fernet). OBLIGATOIRE en
# prod : sans elle, les tokens WhatsApp/Insta/SMTP des salons seraient en clair en base.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | gcloud secrets create JENNY_MASTER_KEY --data-file=-

# Secret d'app Meta (vérification de signature des webhooks WhatsApp/Instagram).
printf 'votre_app_secret_meta'            | gcloud secrets create JENNY_FACEBOOK_APP_SECRET --data-file=-

# Inbound email (SendGrid/Mailgun) : secret partagé long et aléatoire.
python -c "import secrets; print(secrets.token_urlsafe(32))" \
  | gcloud secrets create JENNY_EMAIL_INBOUND_SECRET --data-file=-
```

> Les **tokens WhatsApp/Instagram/SMTP ne sont plus des secrets d'environnement** :
> chaque salon les colle dans l'UI **Intégrations** (stockés en base, chiffrés via
> `JENNY_MASTER_KEY`). Voir §11.

## 5. Build & push des images

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=$REGION,_REPO=$REPO,_API_URL=https://REMPLACER-APRES-1ER-DEPLOY.run.app,_SITE_URL=https://REMPLACER-PAR-URL-FRONT.run.app
```
(Au 1er passage, mettez des URL bidon ; rebuildez le frontend une fois les URL connues — voir §8.)

- `_API_URL` → `NEXT_PUBLIC_API_URL`, `_SITE_URL` → `NEXT_PUBLIC_SITE_URL` : deux variables
  **publiques** Next, inlinées **au build** (les changer = rebuilder le frontend).
  `NEXT_PUBLIC_SITE_URL` sert à `metadataBase` (og:image, canonical, sitemap) ; vide,
  les balises OG pointent sur `localhost`.
- L'image API télécharge mpnet pendant le build (une fois, ~1,1 Go) puis vérifie qu'il se
  charge hors ligne : si cette étape échoue, l'image n'est pas produite.

## 6. Migrations puis réindexation KB (Cloud Run Jobs)

⚠️ Les migrations **ne doivent pas** tourner à chaque démarrage d'instance (course entre
réplicas). L'`entrypoint` le fait en dev ; en prod, lancez-les via un Job dédié et mettez
`RUN_MIGRATIONS=0` / `JENNY_AUTO_SEED=0` sur le service API.

À **chaque release**, dans cet ordre :

1. `alembic upgrade head` (schéma) ;
2. `python scripts/reindex_kb.py --rechunk` (base de connaissances) — **obligatoire** dès
   que le modèle d'embedding ou le découpage change, sans risque sinon (relançable, sûr
   pendant que l'API tourne : chaque entrée est relue sous verrou puis commitée seule).
   Essai à blanc : `--rechunk --dry-run`.

```bash
IMG=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest
DBURL='postgresql+asyncpg://postgres:UN_MDP_FORT@/jenny?host=/cloudsql/'$PROJECT_ID:$REGION:jenny-pg

# 1) schéma
gcloud run jobs create jenny-migrate --image=$IMG --region=$REGION \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --set-env-vars=JENNY_DATABASE_URL="$DBURL" \
  --command=alembic --args=upgrade,head
gcloud run jobs execute jenny-migrate --region=$REGION --wait

# 2) KB : re-découpage + vecteurs (mpnet chargé hors ligne → 2 Gi mini)
gcloud run jobs create jenny-reindex --image=$IMG --region=$REGION \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --set-env-vars=JENNY_DATABASE_URL="$DBURL" \
  --memory=2Gi --cpu=2 --task-timeout=1800 \
  --command=python --args=scripts/reindex_kb.py,--rechunk
gcloud run jobs execute jenny-reindex --region=$REGION --wait

# Créer le super-admin (une fois) : même image avec --command=python --args=-m,jenny.scripts.create_admin
```
Ces Jobs n'ont pas `JENNY_ENV=prod` : ils n'ont donc pas besoin des secrets JWT/Fernet.

## 7. Déployer l'API

`$DBURL` : défini au §6.
```bash
gcloud run deploy jenny-api \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest \
  --region=$REGION --port=8080 --allow-unauthenticated \
  --set-cloudsql-instances=$PROJECT_ID:$REGION:jenny-pg \
  --vpc-connector=jenny-conn \
  --set-env-vars=JENNY_ENV=prod,JENNY_REQUIRE_AUTH=true,RUN_MIGRATIONS=0,JENNY_AUTO_SEED=0 \
  --set-env-vars=JENNY_DATABASE_URL="$DBURL" \
  --set-env-vars=JENNY_REDIS_URL=redis://REDIS_IP:6379/0 \
  --set-env-vars=JENNY_LLM_PROVIDER=groq \
  --set-secrets=JENNY_JWT_SECRET=JENNY_JWT_SECRET:latest,JENNY_GROQ_API_KEY=JENNY_GROQ_API_KEY:latest,JENNY_STRIPE_SECRET_KEY=JENNY_STRIPE_SECRET_KEY:latest,JENNY_MASTER_KEY=JENNY_MASTER_KEY:latest,JENNY_FACEBOOK_APP_SECRET=JENNY_FACEBOOK_APP_SECRET:latest,JENNY_EMAIL_INBOUND_SECRET=JENNY_EMAIL_INBOUND_SECRET:latest \
  --cpu=2 --memory=4Gi --min-instances=0 --max-instances=4 --timeout=120

# Une fois l'URL de l'API connue, repassez-la en variable pour que les URLs de
# webhook données à Meta soient correctes :
API_URL=$(gcloud run services describe jenny-api --region=$REGION --format='value(status.url)')
gcloud run services update jenny-api --region=$REGION \
  --update-env-vars=JENNY_PUBLIC_API_BASE_URL="$API_URL"
```
- `--port=8080` : l'image PROD (`docker/api.prod.Dockerfile`, utilisée par `cloudbuild.yaml`)
  écoute sur `$PORT` (8080). Elle embarque **torch CPU** (image bien plus légère que le wheel
  CUDA) et les seules dépendances de prod. `RUN_MIGRATIONS=0` (les migrations passent par le
  Job §6). L'image de dev `docker/api.Dockerfile` écoute, elle, sur 8000.
- `--memory=4Gi` : PyTorch + mpnet (partagé entre RAG et intention, chargé une seule fois)
  et la tête d'intention. `--readiness` : sonde `/ready` (renvoie 503 si Postgres/Redis KO).
- LLM : on garde le modèle par défaut du code (`openai/gpt-oss-120b` chez Groq) ;
  `llama-3.3-70b-versatile` a été **retiré** par Groq (404 → réponses templates).
- Sans Redis : `--max-instances=1` et `WEB_CONCURRENCY=1` (voir §3). Les valeurs ci-dessus
  (`--max-instances=4`) supposent Memorystore branché.

## 8. Déployer le frontend

Récupérez l'URL de l'API (`gcloud run services describe jenny-api --region=$REGION --format='value(status.url)'`),
**rebuildez le frontend** avec cette URL (`_API_URL`) et l'URL publique du frontend
(`_SITE_URL`, connue après le 1er déploiement ou votre domaine), puis :
```bash
gcloud run deploy jenny-frontend \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/frontend:latest \
  --region=$REGION --port=8080 --allow-unauthenticated \
  --cpu=1 --memory=512Mi --min-instances=0 --max-instances=4
```
Autorisez ensuite l'origine du frontend côté API :
```bash
FRONT_URL=$(gcloud run services describe jenny-frontend --region=$REGION --format='value(status.url)')
gcloud run services update jenny-api --region=$REGION \
  --update-env-vars=JENNY_CORS_ORIGINS=$FRONT_URL,JENNY_APP_BASE_URL=$FRONT_URL
```

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

## 11. Connecter les canaux (WhatsApp / Instagram / Email)

Une fois l'API + le frontend en ligne, **chaque salon connecte ses canaux depuis
l'UI** (page **Intégrations**) — aucune variable d'env à toucher :

1. **WhatsApp / Instagram** (Meta Cloud API, une App Meta partagée) :
   - Dans l'UI, cliquer **Connecter** → coller le **Phone Number ID** (WhatsApp) /
     **Page ID** (Instagram) + le **token permanent** (généré via un *Utilisateur
     Système* Meta — le token de test expire en 24 h).
   - L'UI affiche l'**URL de webhook** (`<API_URL>/api/v1/webhooks/whatsapp` ou
     `/instagram`) et le **Verify Token** : les coller dans Meta → *Webhooks* →
     s'abonner à `messages`. La vérification (GET challenge) accepte ce token.
   - `JENNY_FACEBOOK_APP_SECRET` (secret §4) valide la signature des webhooks.
   - Bouton **Tester** = ping réel de l'API Meta avec le token enregistré.
2. **Email** : coller SMTP (envoi) + IMAP (réception) dans l'UI. La réponse depuis
   le dashboard part par SMTP. (Réception IMAP par salon = chantier suivant ; le
   webhook `<API_URL>/api/v1/ingest/email/inbound` + en-tête `X-Jenny-Inbound-Secret`
   fonctionne déjà pour SendGrid/Mailgun.)

Tant qu'un canal n'a pas d'identifiants, il **reçoit** quand même (webhook) mais
l'**envoi est désactivé** (badge « envoi désactivé ») — jamais d'erreur bloquante.

## 11.5 Activer les paiements Stripe (acompte anti-no-show)

Le code est prêt (Checkout Session réelle + webhook signé qui confirme le RDV).
Pour l'allumer sur la démo — **mode test suffit** pour la soutenance :

1. **Clés Stripe** (Dashboard Stripe → Developers → API keys, en mode test) :
   ```bash
   printf 'sk_test_xxx' | gcloud secrets versions add JENNY_STRIPE_SECRET_KEY --data-file=-
   printf 'whsec_xxx'   | gcloud secrets create JENNY_STRIPE_WEBHOOK_SECRET --data-file=-   # 1re fois
   ```
2. **Câbler le secret webhook + l'URL front** sur le service. Le webhook lit
   `JENNY_STRIPE_WEBHOOK_SECRET` ; les liens de paiement (`/book/merci`, `/book/annule`)
   utilisent `JENNY_APP_BASE_URL` = **URL du frontend** (pas de l'API) :
   ```bash
   FRONT_URL=$(gcloud run services describe jenny-frontend --region=$REGION --format='value(status.url)')
   gcloud run services update jenny-api --region=$REGION \
     --update-secrets=JENNY_STRIPE_WEBHOOK_SECRET=JENNY_STRIPE_WEBHOOK_SECRET:latest \
     --update-env-vars=JENNY_APP_BASE_URL=$FRONT_URL \
     --no-cpu-throttling
   ```
   `--no-cpu-throttling` : les réponses WhatsApp partent en tâche de fond APRÈS la
   réponse HTTP (FastAPI `BackgroundTasks`) ; sans CPU alloué en continu, Cloud Run
   pourrait les couper.
3. **Déclarer le webhook chez Stripe** (Dashboard → Developers → Webhooks → Add endpoint) :
   - URL : `<API_URL>/api/v1/payments/stripe`
   - Événements : `checkout.session.completed` (+ `payment_intent.succeeded` en option)
   - Copier le *Signing secret* (`whsec_...`) → c'est la valeur de l'étape 1.
4. **Activer l'acompte par salon** : dashboard → réglages du salon (« cerveau ») →
   activer l'acompte + le pourcentage. À la prochaine résa, Jenny renvoie le lien de paiement.

Test carte : `4242 4242 4242 4242`, date future, CVC quelconque. En local sans
domaine public : `stripe listen --forward-to <API_URL>/api/v1/payments/stripe`.

## 12. Ce qui reste à faire / limites connues

- **LLM** : Groq par défaut, OpenAI en option (`JENNY_LLM_PROVIDER` + clé).
- **Email** : réception IMAP *par salon* + auto-réponse Jenny par email = chantier suivant
  (le polling IMAP global + le webhook inbound marchent déjà ; la réponse manuelle aussi).
- **Image API lourde** (torch CPU + mpnet ~1,1 Go embarqué) : voir §5/§7.
- **Changer de modèle d'embedding** : modifier `JENNY_EMBEDDINGS_MODEL` ne suffit pas —
  l'image est hors ligne (rebuild avec `--build-arg EMBED_MODEL=…`), la colonne `vector(768)`
  doit correspondre, et `scripts/reindex_kb.py --rechunk` est obligatoire (§6).
- **Avant une release** : la CI (`.github/workflows/ci.yml`) doit être verte — migrations
  sur base vierge, dérive modèles/migrations bloquée, tests sans réseau, build du front.
- Variables d'environnement complètes : voir [`.env.example`](.env.example) (dont
  `JENNY_MASTER_KEY` et `JENNY_PUBLIC_API_BASE_URL`, nouveaux).
