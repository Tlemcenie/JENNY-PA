"""business_config_fields — Champs de configuration du business.

Ajoute à la table ``businesses`` les colonnes éditables depuis l'écran
« Configuration du compte » : ``phone``, ``description`` et ``timezone``.
``timezone`` reçoit un server_default pour remplir les lignes existantes.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("businesses", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "businesses",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Europe/Paris",
        ),
    )


def downgrade() -> None:
    op.drop_column("businesses", "timezone")
    op.drop_column("businesses", "description")
    op.drop_column("businesses", "phone")
