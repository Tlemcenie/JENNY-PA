"""Filtre autogenerate : objets hors modèles ORM.

Sans lui, ``alembic revision --autogenerate`` voit ces objets « en trop »
et génère des DROP (base RAG, index perf, anti double réservation...).
"""

from __future__ import annotations

from typing import Any

# tables en SQL brut, sans modèle
TABLES_HORS_ORM = frozenset({"document_embeddings"})

# colonnes en SQL brut (pgvector, tsvector)
COLONNES_HORS_ORM = frozenset(
    {
        ("document_embeddings", "embedding"),
        ("document_embeddings", "content_tsv"),
    }
)

# index posés en SQL brut
INDEX_HORS_ORM = frozenset(
    {
        # recherche texte (GIN tsvector)
        "ix_messages_content_fts",
        # RAG (jen_raghnsw_h1i2)
        "ix_document_embeddings_embedding_hnsw",
        "ix_document_embeddings_content_tsv",
        "idx_document_embeddings_embedding",
        # EXCLUDE gist, vu comme index
        "appointments_no_overlap",
        # index perf (jen_perfidx2_i2j3)
        "ix_messages_business_received",
        "ix_messages_business_created",
        "ix_messages_conversation_created",
        "ix_messages_customer_id",
        "ix_conversations_business_status",
        "ix_conversations_business_last_msg",
        "ix_conversations_business_recency",
        "ix_appointments_end_at",
        "ix_customers_business_instagram",
        "ix_customers_business_messenger",
    }
)

# contraintes posées en SQL brut
CONTRAINTES_HORS_ORM = frozenset({"appointments_no_overlap", "appointments_end_after_start"})

# créés par migration, oubliés des modèles
# en base seulement : jamais de DROP
PROTEGES = frozenset(
    {
        "uq_payments_provider_external",
        "ix_customer_transactions_provider_external",
        "ix_customer_transactions_business_occurred",
        "ix_orders_business_reference",
        "ix_support_tickets_business_reference",
    }
)

_CONTRAINTES = ("unique_constraint", "foreign_key_constraint", "check_constraint")


def _table_name(obj: Any) -> str | None:
    """Table de l'objet, si connue."""
    table = getattr(obj, "table", None)
    return getattr(table, "name", None)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Ignore ce qui est géré à la main dans les migrations."""
    if type_ == "table":
        return name not in TABLES_HORS_ORM
    table = _table_name(obj)
    if table in TABLES_HORS_ORM:
        return False
    if type_ == "column" and (table, name) in COLONNES_HORS_ORM:
        return False
    if type_ == "index" and name in INDEX_HORS_ORM:
        return False
    if type_ in _CONTRAINTES and name in CONTRAINTES_HORS_ORM:
        return False
    # absent des modèles : on garde
    return not (reflected and compare_to is None and name in PROTEGES)


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Ne relit même pas les tables hors ORM."""
    return not (type_ == "table" and name in TABLES_HORS_ORM)
