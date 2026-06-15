"""Fidélisation : suivi post-RDV (avis + relance de re-réservation).

Revision ID: jen_followup_a7b8
Revises: jen_rgpd_f6a7
Create Date: 2026-06-15 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "jen_followup_a7b8"
down_revision: Union[str, None] = "jen_rgpd_f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("review_request_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("rebook_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "rebook_reminder_sent_at")
    op.drop_column("appointments", "review_request_sent_at")
