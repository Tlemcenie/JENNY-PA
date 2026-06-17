#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Déploiement de Jenny en PROD (GCP Cloud Run) depuis le code local.
#
#   ./deploy.sh              → build + redéploie API & frontend
#   ./deploy.sh --migrate    → idem + applique les migrations DB (si schéma changé)
#
# Rien n'est automatique : le cloud ne bouge QUE quand tu lances ce script.
# Modifier le code en local n'a AUCUN effet sur la prod tant que tu n'as pas
# lancé ./deploy.sh.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT=jenny-499621
REGION=europe-west9
REPO=jenny
API_URL=https://jenny-api-312560265552.europe-west9.run.app
FRONT_URL=https://jenny-frontend-312560265552.europe-west9.run.app
AR=$REGION-docker.pkg.dev/$PROJECT/$REPO

echo "▶ 1/4 — Build des 3 images (Cloud Build, ~10 min)…"
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=$REGION,_REPO=$REPO,_API_URL=$API_URL --project=$PROJECT

if [[ "${1:-}" == "--migrate" ]]; then
  echo "▶ 2/4 — Migrations DB (alembic upgrade head)…"
  gcloud run jobs execute jenny-migrate --region=$REGION --project=$PROJECT --wait
else
  echo "▶ 2/4 — Migrations sautées (ajoute --migrate si tu as changé le schéma)."
fi

echo "▶ 3/4 — Redéploiement de l'API (garde env + secrets existants)…"
gcloud run deploy jenny-api --image=$AR/api:latest --region=$REGION --project=$PROJECT

echo "▶ 4/4 — Redéploiement du frontend…"
gcloud run deploy jenny-frontend --image=$AR/frontend:latest --region=$REGION --project=$PROJECT

echo ""
echo "✅ Déployé en prod."
echo "   Site : $FRONT_URL"
echo "   API  : $API_URL/ready"
