"""Devis (quotes) — devis réels générés par Jenny depuis le catalogue.

Revision ID: jen_quotes_e1f2
Revises: jen_chancreds_d0e1
Create Date: 2026-06-17 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "jen_quotes_e1f2"
down_revision: Union[str, None] = "jen_chancreds_d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quotes",
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
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("items", sa.JSON(), nullable=True),
        sa.Column("total_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("sent_to_email", sa.String(length=255), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quotes_business_id", "quotes", ["business_id"])
    op.create_index("ix_quotes_customer_id", "quotes", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_quotes_customer_id", table_name="quotes")
    op.drop_index("ix_quotes_business_id", table_name="quotes")
    op.drop_table("quotes")
