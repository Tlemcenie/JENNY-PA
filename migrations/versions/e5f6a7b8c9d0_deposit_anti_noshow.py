"""Acompte anti-no-show : politique salon + suivi par rendez-vous.

Revision ID: jen_deposit_e5f6
Revises: jen_waitlist_d4e5
Create Date: 2026-06-15 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "jen_deposit_e5f6"
down_revision: Union[str, None] = "jen_waitlist_d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Politique d'acompte côté salon.
    op.add_column(
        "businesses",
        sa.Column(
            "deposit_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "businesses",
        sa.Column("deposit_percent", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "businesses",
        sa.Column(
            "deposit_min_cents", sa.Integer(), server_default="1000", nullable=False
        ),
    )

    # Suivi de l'acompte sur chaque rendez-vous.
    op.add_column("appointments", sa.Column("deposit_cents", sa.Integer(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("deposit_status", sa.String(length=20), server_default="none", nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "deposit_payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("appointments", "deposit_payment_id")
    op.drop_column("appointments", "deposit_status")
    op.drop_column("appointments", "deposit_cents")
    op.drop_column("businesses", "deposit_min_cents")
    op.drop_column("businesses", "deposit_percent")
    op.drop_column("businesses", "deposit_enabled")
