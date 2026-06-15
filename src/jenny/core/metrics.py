"""Compteurs Prometheus partagés."""

from prometheus_client import Counter

HTTP_REQUESTS = Counter(
    "jenny_http_requests_total",
    "Requêtes HTTP Jenny",
    ["method", "path_group"],
)

WEBHOOK_DUPLICATES = Counter(
    "jenny_webhook_duplicates_total",
    "Livraisons webhook ignorées (idempotence)",
    ["channel"],
)

ARQ_JOBS = Counter(
    "jenny_arq_jobs_total",
    "Jobs ARQ enfilés",
    ["job_name"],
)
