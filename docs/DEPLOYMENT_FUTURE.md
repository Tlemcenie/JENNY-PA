# Déploiement futur (réflexion)

Ce document fixe des **pistes**, pas des décisions. L’objectif actuel est un **projet stable en local** puis une montée en charge sur le cloud.

## Phase actuelle : local

- API FastAPI, Postgres + Redis + worker ARQ, MLflow en Docker Compose.
- Modèles Intent / NER et tests e2e sur la machine de dev / CI.

## Cible probable : Google Cloud Platform (GCP)

Alignements naturels avec la stack actuelle :

- **Cloud Run** ou **GKE** pour l’API et le worker (conteneurs déjà Dockerisés).
- **Cloud SQL** (PostgreSQL) avec extension **pgvector** pour le RAG en production.
- **Memorystore (Redis)** pour ARQ et cache.
- **Artifact Registry** pour images Docker et éventuellement artefacts ML.
- **Secret Manager** pour clés API et connexions.

## Données & orchestration (à trancher plus tard)

| Option | Rôle typique |
|--------|----------------|
| **Apache Airflow** (Composer sur GCP) | Pipelines planifiés : ingestion, entraînement, scoring batch. |
| **dbt** | Modélisation analytique dans l’entrepôt (tables de faits / dimensions, qualité). |
| **Databricks** | Spark / ML à grande échelle si volumétrie ou notebooks d’équipe ; souvent redondant avec une stack GCP + Vertex AI si tout reste sur Google. |
| **GCP seul** (Cloud Functions, Scheduler, Dataflow) | Suffisant pour des flux plus simples sans cluster Spark. |

Une combinaison fréquente : **Airflow** pour l’orchestration, **BigQuery + dbt** pour la couche analytics, **Vertex AI** ou entraînement custom sur **Compute Engine / GKE** pour le ML lourd — à valider selon volumétrie et équipe.

## CI/CD

- **Court terme** : GitHub Actions (déjà dans le dépôt) pour valider chaque PR.
- **Ensuite** : pipeline de build d’images, push vers Artifact Registry, déploiement sur Cloud Run (ou équivalent) — souvent **Cloud Build** ou **GitHub Actions** + déploiement GCP.

Quand le besoin sera clair (trafic, budget, équipe data), on pourra détailler une architecture cible dans un ADR (Architecture Decision Record).
