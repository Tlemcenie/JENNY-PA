"""waitlist_entries (liste d'attente anti-no-show).

Revision ID: jen_waitlist_d4e5
Revises: jen_dayrem_c3d4
Create Date: 2026-06-15 09:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "jen_waitlist_d4e5"
down_revision: Union[str, None] = "jen_dayrem_c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service", sa.String(length=120), nullable=True),
        sa.Column("desired_window", sa.String(length=200), nullable=True),
        sa.Column("customer_name", sa.String(length=120), nullable=True),
        sa.Column("customer_contact", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="waiting", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_waitlist_entries_business_id", "waitlist_entries", ["business_id"])
    op.create_index("ix_waitlist_entries_status", "waitlist_entries", ["status"])


def downgrade() -> None:
    op.drop_table("waitlist_entries")
