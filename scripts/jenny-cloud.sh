#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# « Mode démo » GCP — n'allume la prod QUE quand tu en as besoin.
#
#   ./scripts/jenny-cloud.sh stop    → éteint Cloud SQL (facturation ~0€ idle)
#   ./scripts/jenny-cloud.sh start   → rallume Cloud SQL (prêt en ~1-2 min)
#   ./scripts/jenny-cloud.sh status  → état + rappel des coûts
#
# Redis a été SUPPRIMÉ volontairement : l'app bascule en mémoire (mono-instance,
# suffisant pour une démo). Pour le recréer un jour de vrai lancement :
#   ./scripts/jenny-cloud.sh redis-create
#
# Cloud Run tombe déjà à zéro tout seul (min-instances=0) → rien à faire.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT=jenny-499621
REGION=europe-west9
SQL=jenny-pg
REDIS=jenny-redis
API=jenny-api
FRONT_URL=https://jenny-frontend-312560265552.europe-west9.run.app

cmd="${1:-status}"

case "$cmd" in
  stop)
    echo "▶ Extinction de Cloud SQL ($SQL)…"
    gcloud sql instances patch "$SQL" --activation-policy NEVER \
      --project "$PROJECT" --quiet
    echo "✅ SQL éteint. Coût idle ≈ 0€ (tu ne paies plus que ~1-2€/mois de stockage disque)."
    echo "   La prod répond mais chat/login/RDV sont KO tant que tu ne fais pas 'start'."
    ;;

  start)
    echo "▶ Rallumage de Cloud SQL ($SQL)…"
    gcloud sql instances patch "$SQL" --activation-policy ALWAYS \
      --project "$PROJECT" --quiet
    echo "   Attente que l'instance soit RUNNABLE…"
    for i in $(seq 1 30); do
      st=$(gcloud sql instances describe "$SQL" --project "$PROJECT" \
            --format="value(state)" 2>/dev/null || echo "?")
      [[ "$st" == "RUNNABLE" ]] && break
      sleep 5
    done
    echo "✅ SQL prêt. Démo disponible : $FRONT_URL"
    echo "   ⚠️  Pense à './scripts/jenny-cloud.sh stop' après la démo."
    ;;

  redis-create)
    echo "▶ (Re)création de Memorystore Redis 1 GB — ~35€/mois tant qu'il existe…"
    gcloud redis instances create "$REDIS" --size=1 --region="$REGION" \
      --redis-version=redis_7_0 --tier=basic --project "$PROJECT"
    ip=$(gcloud redis instances describe "$REDIS" --region="$REGION" \
          --project "$PROJECT" --format="value(host)")
    echo "▶ Mise à jour de l'API (JENNY_REDIS_URL=redis://$ip:6379/0) + redeploy…"
    gcloud run services update "$API" --region="$REGION" --project "$PROJECT" \
      --update-env-vars="JENNY_REDIS_URL=redis://$ip:6379/0"
    echo "✅ Redis actif et branché."
    ;;

  status)
    echo "── État prod Jenny ──"
    sql_state=$(gcloud sql instances describe "$SQL" --project "$PROJECT" \
                 --format="value(settings.activationPolicy,state)" 2>/dev/null || echo "absent")
    echo "Cloud SQL   : $sql_state   (ALWAYS=allumé/payant, NEVER=éteint/~0€)"
    redis_state=$(gcloud redis instances list --region="$REGION" --project "$PROJECT" \
                   --format="value(name)" 2>/dev/null | grep -c "$REDIS" || true)
    if [[ "$redis_state" == "0" ]]; then
      echo "Redis       : supprimé ✅ (app en mémoire, 0€)"
    else
      echo "Redis       : PRÉSENT ⚠️ (~35€/mois — 'redis-delete' pour couper)"
    fi
    echo "Cloud Run   : min-instances=0 (scale-to-zero, ~0€ idle)"
    ;;

  redis-delete)
    echo "▶ Suppression de Redis ($REDIS)…"
    gcloud redis instances delete "$REDIS" --region="$REGION" \
      --project "$PROJECT" --quiet
    echo "✅ Redis supprimé. L'app bascule en mémoire automatiquement."
    ;;

  *)
    echo "Usage: $0 {stop|start|status|redis-create|redis-delete}"
    exit 1
    ;;
esac
