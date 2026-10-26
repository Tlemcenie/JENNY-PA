"""Perf : index manquants (inbox, messages, rappels, identité client).

Chaque index suit une requête réelle :
- inbox : tri coalesce(last_message_at, created_at) + dernier message par conv ;
- messages : pagination curseur (received_at, id), stats par jour, FK client ;
- appointments.end_at : avis et relances du worker ;
- customers : retrouver un client Instagram / Messenger.

Pas de CONCURRENTLY : la migration reste dans sa transaction.
L'unique sur payments existe déjà : uq_payments_provider_external.

Revision ID: jen_perfidx2_i2j3
Revises: jen_nooverlap_g1h2
"""

from typing import Union

from alembic import op

revision: str = "jen_perfidx2_i2j3"
down_revision: Union[str, None] = "jen_nooverlap_g1h2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# nom -> (table, colonnes, filtre)
INDEXES: dict[str, tuple[str, str, str | None]] = {
    "ix_messages_business_received": ("messages", "business_id, received_at, id", None),
    "ix_messages_business_created": ("messages", "business_id, created_at", None),
    "ix_messages_conversation_created": ("messages", "conversation_id, created_at, id", None),
    "ix_messages_customer_id": ("messages", "customer_id", None),
    "ix_conversations_business_status": ("conversations", "business_id, status", None),
    "ix_conversations_business_last_msg": ("conversations", "business_id, last_message_at", None),
    "ix_conversations_business_recency": (
        "conversations",
        "business_id, (coalesce(last_message_at, created_at))",
        None,
    ),
    "ix_appointments_end_at": ("appointments", "end_at", None),
    "ix_customers_business_instagram": (
        "customers",
        "business_id, instagram_handle",
        "instagram_handle IS NOT NULL",
    ),
    "ix_customers_business_messenger": (
        "customers",
        "business_id, messenger_id",
        "messenger_id IS NOT NULL",
    ),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # index partiels/expression : Postgres
    for name, (table, cols, where) in INDEXES.items():
        clause = f" WHERE {where}" if where else ""
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols}){clause}")
    # stats à jour pour le planner
    for table in sorted({t for t, _c, _w in INDEXES.values()}):
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in reversed(list(INDEXES)):
        op.execute(f"DROP INDEX IF EXISTS {name}")
