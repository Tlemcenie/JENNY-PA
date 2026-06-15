"""conversation_threading_fields — Champs de threading et métadonnées de conversation.

Ajoute à la table ``conversations`` les colonnes attendues par le service
d'ingestion et le schéma ``ConversationRead`` mais absentes du modèle :

- ``external_conversation_id`` : ID de thread externe (email In-Reply-To,
  ``wa:<sender>`` WhatsApp…), indexé pour la résolution de conversation.
- ``priority_level`` : priorité de la conversation (server_default "medium").
- ``first_message_at`` : horodatage du premier message.
- ``last_message_preview`` : aperçu du dernier message.

Sans ces colonnes, l'ingestion formulaire/email/webhook échouait
(``TypeError: 'external_conversation_id' is an invalid keyword argument``).

Revision ID: f1a2b3c4d5e6
Revises: e3f4a5b6c7d8
Create Date: 2026-06-13 22:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("external_conversation_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_conversations_external_conversation_id",
        "conversations",
        ["external_conversation_id"],
    )
    op.add_column(
        "conversations",
        sa.Column(
            "priority_level",
            sa.String(length=20),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("last_message_preview", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "last_message_preview")
    op.drop_column("conversations", "first_message_at")
    op.drop_column("conversations", "priority_level")
    op.drop_index("ix_conversations_external_conversation_id", table_name="conversations")
    op.drop_column("conversations", "external_conversation_id")
