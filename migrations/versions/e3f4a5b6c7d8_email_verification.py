"""email_verification — Confirmation d'email par code à l'inscription.

Ajoute à la table ``users`` les colonnes nécessaires à la confirmation de
l'adresse email : un drapeau ``email_verified``, le hash du code à 6 chiffres,
sa date d'expiration, un compteur de tentatives et la date du dernier envoi.

Les comptes déjà existants sont marqués comme vérifiés afin de ne pas les
bloquer rétroactivement (seules les nouvelles inscriptions sont concernées).

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_code_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Comptes existants : considérés vérifiés pour ne pas les bloquer.
    op.execute("UPDATE users SET email_verified = true")


def downgrade() -> None:
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verification_attempts")
    op.drop_column("users", "email_verification_expires_at")
    op.drop_column("users", "email_verification_code_hash")
    op.drop_column("users", "email_verified")
