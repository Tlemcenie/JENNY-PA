"""Ajoute password_hash a la table users pour le signup email/password.

Revision ID: a7f3b2d1e9c8
Revises: b9c8d7e6f5a4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7f3b2d1e9c8"
down_revision: Union[str, None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
