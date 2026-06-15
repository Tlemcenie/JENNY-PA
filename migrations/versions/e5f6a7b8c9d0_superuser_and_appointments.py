"""users.is_superuser + table appointments (admin & calendrier).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-14 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "appointments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "business_id",
            _uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            _uuid(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("conversation_id", _uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="scheduled", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_appointments_business_id", "appointments", ["business_id"])
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"])
    op.create_index("ix_appointments_conversation_id", "appointments", ["conversation_id"])
    op.create_index("ix_appointments_start_at", "appointments", ["start_at"])


def downgrade() -> None:
    op.drop_index("ix_appointments_start_at", table_name="appointments")
    op.drop_index("ix_appointments_conversation_id", table_name="appointments")
    op.drop_index("ix_appointments_customer_id", table_name="appointments")
    op.drop_index("ix_appointments_business_id", table_name="appointments")
    op.drop_table("appointments")
    op.drop_column("users", "is_superuser")
