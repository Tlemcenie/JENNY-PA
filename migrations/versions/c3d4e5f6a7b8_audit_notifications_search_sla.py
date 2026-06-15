"""audit_logs, notifications, sla_rules, recherche plein-texte messages.

Nouveau lot back :
- table ``audit_logs`` : journal « qui a fait quoi » (#16).
- table ``notifications`` : centre de notifications par agent (#14/#15).
- ``businesses.sla_rules`` : SLA par priorité/canal (JSON) (#7).
- index GIN plein-texte sur ``messages.content_text`` (Postgres only) (#8).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14 09:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid() -> sa.types.TypeEngine:
    """UUID natif Postgres, repli sur CHAR(36) ailleurs (SQLite de test)."""
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.create_table(
        "audit_logs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "business_id",
            _uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_business_id", "audit_logs", ["business_id"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "business_id",
            _uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("conversation_id", _uuid(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_notifications_business_id", "notifications", ["business_id"])
    op.create_index("ix_notifications_recipient", "notifications", ["recipient"])
    op.create_index("ix_notifications_conversation_id", "notifications", ["conversation_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.add_column("businesses", sa.Column("sla_rules", sa.JSON(), nullable=True))

    # Index plein-texte GIN sur le contenu des messages (recherche rapide).
    # Expression-index Postgres uniquement ; les autres dialectes retombent
    # sur un LIKE applicatif (pas d'index spécifique nécessaire).
    if is_pg:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_messages_content_fts "
            "ON messages USING gin (to_tsvector('french', coalesce(content_text, '')))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_messages_content_fts")
    op.drop_column("businesses", "sla_rules")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_conversation_id", table_name="notifications")
    op.drop_index("ix_notifications_recipient", table_name="notifications")
    op.drop_index("ix_notifications_business_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_index("ix_audit_logs_business_id", table_name="audit_logs")
    op.drop_table("audit_logs")
