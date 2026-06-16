"""Devis : ventilation TVA (HT / TVA / taux) pour un vrai devis.

Revision ID: jen_quotevat_f2a3
Revises: jen_quotes_e1f2
Create Date: 2026-06-17 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "jen_quotevat_f2a3"
down_revision: Union[str, None] = "jen_quotes_e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("total_ht_cents", sa.Integer(), server_default="0", nullable=False))
    op.add_column("quotes", sa.Column("total_tva_cents", sa.Integer(), server_default="0", nullable=False))
    op.add_column("quotes", sa.Column("vat_rate", sa.Float(), server_default="0.20", nullable=False))


def downgrade() -> None:
    op.drop_column("quotes", "vat_rate")
    op.drop_column("quotes", "total_tva_cents")
    op.drop_column("quotes", "total_ht_cents")
