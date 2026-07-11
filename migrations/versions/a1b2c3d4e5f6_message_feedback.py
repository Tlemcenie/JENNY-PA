"""Feedback utilisateur 👍/👎 sur les réponses de Jenny (table message_feedback).

Revision ID: jen_msgfeedback_a1b2
Revises: jen_quotevat_f2a3
Create Date: 2026-07-07 15:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "jen_msgfeedback_a1b2"
down_revision: Union[str, None] = "jen_quotevat_f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", name="uq_message_feedback_message"),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])
    op.create_index("ix_message_feedback_conversation_id", "message_feedback", ["conversation_id"])
    op.create_index("ix_message_feedback_business_id", "message_feedback", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_message_feedback_business_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_conversation_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_id", table_name="message_feedback")
    op.drop_table("message_feedback")
