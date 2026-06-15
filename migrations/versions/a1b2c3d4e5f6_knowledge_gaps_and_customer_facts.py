"""knowledge_gaps + customer_facts (boucle d'apprentissage + mémoire client).

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-06-14 21:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "jen_kgaps_a1b2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_key", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=True),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by", sa.String(length=255), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_to_kb", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("knowledge_entry_id", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_knowledge_gaps_business_id", "knowledge_gaps", ["business_id"])
    op.create_index("ix_knowledge_gaps_conversation_id", "knowledge_gaps", ["conversation_id"])
    op.create_index("ix_knowledge_gaps_question_key", "knowledge_gaps", ["question_key"])
    op.create_index("ix_knowledge_gaps_status", "knowledge_gaps", ["status"])

    op.create_table(
        "customer_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("fact_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=30), server_default="other", nullable=False),
        sa.Column("source", sa.String(length=20), server_default="conversation", nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_customer_facts_business_id", "customer_facts", ["business_id"])
    op.create_index("ix_customer_facts_customer_id", "customer_facts", ["customer_id"])
    op.create_index("ix_customer_facts_fact_key", "customer_facts", ["fact_key"])


def downgrade() -> None:
    op.drop_table("customer_facts")
    op.drop_table("knowledge_gaps")
