"""features_batch_columns — colonnes pour le lot de 20 features.

- conversations.snoozed_until : report (snooze) d'une conversation.
- conversations.sentiment : sentiment du dernier message client.
- businesses.business_hours : horaires d'ouverture (JSON).
- businesses.auto_reply_message : message auto hors horaires.
- businesses.sla_minutes : seuil SLA configurable par business.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14 07:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("sentiment", sa.String(length=20), nullable=True),
    )
    op.add_column("businesses", sa.Column("business_hours", sa.JSON(), nullable=True))
    op.add_column("businesses", sa.Column("auto_reply_message", sa.Text(), nullable=True))
    op.add_column(
        "businesses",
        sa.Column("sla_minutes", sa.Integer(), server_default="30", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("businesses", "sla_minutes")
    op.drop_column("businesses", "auto_reply_message")
    op.drop_column("businesses", "business_hours")
    op.drop_column("conversations", "sentiment")
    op.drop_column("conversations", "snoozed_until")
