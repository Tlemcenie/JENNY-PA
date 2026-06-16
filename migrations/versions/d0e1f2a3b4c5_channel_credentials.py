"""Identifiants de canal par business (connexion WhatsApp/Instagram/Email réelle).

Ajoute à ``channel_accounts`` :
- ``credentials_`` : JSON des identifiants par business (token Meta, SMTP/IMAP…),
  chiffrés au repos si ``JENNY_MASTER_KEY`` est défini (sinon clair, HTTPS).
- ``webhook_verified_at`` : horodatage de la dernière vérif webhook réussie.
- ``last_error`` : dernier message d'erreur (diagnostic UI).

Revision ID: jen_chancreds_d0e1
Revises: jen_perfidx_c9d0
Create Date: 2026-06-16 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "jen_chancreds_d0e1"
down_revision: Union[str, None] = "jen_perfidx_c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("channel_accounts", sa.Column("credentials_", sa.JSON(), nullable=True))
    op.add_column(
        "channel_accounts",
        sa.Column("webhook_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "channel_accounts",
        sa.Column("last_error", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_accounts", "last_error")
    op.drop_column("channel_accounts", "webhook_verified_at")
    op.drop_column("channel_accounts", "credentials_")
