"""RGPD : customers.anonymized_at (droit à l'effacement).

Revision ID: jen_rgpd_f6a7
Revises: jen_deposit_e5f6
Create Date: 2026-06-15 11:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "jen_rgpd_f6a7"
down_revision: Union[str, None] = "jen_deposit_e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "anonymized_at")
