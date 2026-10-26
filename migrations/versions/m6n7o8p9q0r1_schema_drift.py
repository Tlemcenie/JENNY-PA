"""Base alignée sur les modèles : alembic check à zéro.

- NOT NULL posés là où le modèle les exige (NULL remplis avant) ;
- index en double sur webhook_deliveries.dedup_key retiré : la contrainte
  unique webhook_deliveries_dedup_key_key sert déjà la recherche de dédup ;
- commentaires de colonnes recopiés depuis les modèles.

Rejouable : chaque étape ne change rien si elle est déjà faite.

Revision ID: jen_drift_m6n7
Revises: jen_staffsk_l5m6
"""

from collections.abc import Sequence

from alembic import op

revision: str = "jen_drift_m6n7"
down_revision: str | None = "jen_staffsk_l5m6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# dates : l'autre date, sinon maintenant
_STAMPS = {
    "created_at": "coalesce(updated_at, now())",
    "updated_at": "coalesce(created_at, now())",
}

# table -> colonne -> valeur si NULL
NOT_NULL: dict[str, dict[str, str]] = {
    "business_closures": _STAMPS,
    "businesses": {"is_active": "true"},
    "conversations": {"message_count": "0", "is_escalated": "false"},
    "customer_facts": _STAMPS,
    "knowledge_gaps": _STAMPS,
    "messages": {"has_attachments": "false", "attachment_count": "0", "urgency_flag": "false"},
    "pending_questions": _STAMPS,
    "prestations": _STAMPS,
    "reviews": _STAMPS,
    "waitlist_entries": _STAMPS,
}

DEDUP_INDEX = "ix_webhook_deliveries_dedup_key"

# (table, colonne) -> (avant, modèle)
COMMENTS: dict[tuple[str, str], tuple[str | None, str]] = {
    ("businesses", "email"): ("Email principal", "Email principal du business"),
    ("businesses", "phone"): (None, "Téléphone de contact du business"),
    ("businesses", "description"): (None, "Description / présentation du business"),
    ("businesses", "timezone"): (None, "Fuseau horaire (IANA) du business"),
    ("businesses", "is_active"): ("Business actif", "Business actif ou désactivé"),
    ("businesses", "auto_reply_message"): (
        None,
        "Message envoyé automatiquement hors horaires d'ouverture",
    ),
    ("businesses", "sla_minutes"): (
        None,
        "Seuil SLA par défaut : conversation en retard si en attente depuis +N min",
    ),
    ("businesses", "deposit_enabled"): (None, "Demander un acompte à la réservation"),
    ("businesses", "deposit_percent"): (
        None,
        "Pourcentage du prix de la prestation demandé en acompte (0-100)",
    ),
    ("businesses", "deposit_min_cents"): (
        None,
        "Acompte forfaitaire (centimes) quand le prix de la prestation est inconnu",
    ),
    ("businesses", "reminder_lead_minutes"): (
        None,
        "Délai du rappel « imminent » avant le RDV (minutes)",
    ),
    ("businesses", "day_reminder_lead_hours"): (
        None,
        "Délai du rappel « la veille » avant le RDV (heures)",
    ),
    ("businesses", "loyalty_threshold"): (
        None,
        "Nombre de RDV honorés pour débloquer une récompense fidélité (0 = désactivé)",
    ),
    ("conversations", "external_conversation_id"): (
        None,
        "ID de thread externe (email In-Reply-To, wa:<sender>, ...)",
    ),
    ("conversations", "priority_level"): (None, "low, medium, high, critical"),
    ("conversations", "last_message_preview"): (None, "Aperçu du dernier message"),
    ("conversations", "assigned_to"): (
        "Conseiller humain assigné",
        "Conseiller humain assigné (si escalade)",
    ),
    ("conversations", "summary"): (
        "Résumé de la conversation (LLM)",
        "Résumé de la conversation (généré par LLM)",
    ),
    ("message_events", "event_type"): (
        "ingested, normalized, classified, etc.",
        "Type : ingested, normalized, classified, reply_generated, reply_sent, escalated, error",
    ),
    ("message_events", "status"): (None, "success, failure, skipped"),
    ("message_events", "detail"): (None, "Détails ou message d'erreur"),
    ("message_events", "payload"): (None, "Données associées à l'événement"),
    ("messages", "external_message_id"): (
        "ID côté canal source",
        "ID unique côté canal source (pour déduplication)",
    ),
    ("messages", "channel"): (
        "instagram, whatsapp, messenger, email, form",
        "Canal : instagram, whatsapp, messenger, email, form",
    ),
    ("messages", "content_text"): ("Contenu texte brut", "Contenu texte brut du message"),
    ("messages", "cleaned_text"): (
        "Texte nettoyé post-normalisation",
        "Texte nettoyé (post-normalisation)",
    ),
    ("messages", "language"): ("Langue ISO 639-1", "Langue détectée (ISO 639-1)"),
    ("messages", "status"): (
        None,
        "received, normalizing, normalized, processing, responded, archived",
    ),
    ("messages", "priority"): (
        "Score priorité 1-10 (ML)",
        "Score de priorité (1-10, calculé par ML)",
    ),
    ("messages", "category"): ("Catégorie (ML)", "Catégorie détectée (ML)"),
    ("messages", "sentiment_score"): (
        "Sentiment -1.0 à 1.0",
        "Score de sentiment (-1.0 à 1.0)",
    ),
    ("messages", "source_created_at"): (None, "Timestamp original côté canal source"),
    ("messages", "received_at"): (None, "Timestamp de réception par Jenny"),
    ("messages", "normalized_at"): (None, "Timestamp de normalisation"),
    ("messages", "raw_metadata"): (
        "Payload brut original",
        "Payload brut original du connecteur",
    ),
}


def _is_pg() -> bool:
    """Marche aussi en mode --sql."""
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_pg():
        return  # chaîne Postgres seulement
    for table, cols in NOT_NULL.items():
        # NULL remplis, un par un
        for col, fill in cols.items():
            op.execute(f"UPDATE {table} SET {col} = {fill} WHERE {col} IS NULL")
        alters = ", ".join(f"ALTER COLUMN {col} SET NOT NULL" for col in cols)
        op.execute(f"ALTER TABLE {table} {alters}")
    op.execute(f"DROP INDEX IF EXISTS {DEDUP_INDEX}")
    for (table, col), (old, new) in COMMENTS.items():
        op.alter_column(table, col, comment=new, existing_comment=old)


def downgrade() -> None:
    if not _is_pg():
        return
    for (table, col), (old, new) in COMMENTS.items():
        op.alter_column(table, col, comment=old, existing_comment=new)
    op.execute(f"CREATE INDEX IF NOT EXISTS {DEDUP_INDEX} ON webhook_deliveries (dedup_key)")
    for table, cols in NOT_NULL.items():
        alters = ", ".join(f"ALTER COLUMN {col} DROP NOT NULL" for col in cols)
        op.execute(f"ALTER TABLE {table} {alters}")
