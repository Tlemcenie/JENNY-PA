"""Lot fidélisation/exploitation v2 : fermetures, avis, rappels config, fidélité, notes.

Revision ID: jen_salon2_b8c9
Revises: jen_followup_a7b8
Create Date: 2026-06-15 13:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "jen_salon2_b8c9"
down_revision: Union[str, None] = "jen_followup_a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fermetures exceptionnelles (#89).
    op.create_table(
        "business_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_business_closures_business_id", "business_closures", ["business_id"])

    # Avis clients (#92).
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_reviews_business_id", "reviews", ["business_id"])

    # Rappels configurables (#90) + fidélité (#93) côté salon.
    op.add_column(
        "businesses",
        sa.Column("reminder_lead_minutes", sa.Integer(), server_default="60", nullable=False),
    )
    op.add_column(
        "businesses",
        sa.Column("day_reminder_lead_hours", sa.Integer(), server_default="24", nullable=False),
    )
    op.add_column(
        "businesses",
        sa.Column("loyalty_threshold", sa.Integer(), server_default="10", nullable=False),
    )

    # Notes techniques par RDV (#94).
    op.add_column("appointments", sa.Column("staff_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("appointments", "staff_notes")
    op.drop_column("businesses", "loyalty_threshold")
    op.drop_column("businesses", "day_reminder_lead_hours")
    op.drop_column("businesses", "reminder_lead_minutes")
    op.drop_table("reviews")
    op.drop_table("business_closures")
