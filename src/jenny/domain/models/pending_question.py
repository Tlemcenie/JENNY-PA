"""Question en attente rattachée à une conversation (à traiter par le coiffeur).

Quand, au fil d'un échange, Jenny a besoin d'une info qu'elle n'a pas pour servir
CE client (ou que le client lui pose une question hors de son périmètre), elle la
met de côté ici, rattachée à la conversation. Le coiffeur la voit dans la
conversation, y répond (réponse qui peut être renvoyée au client) ou la traite.

Distinct de ``KnowledgeGap`` (connaissance générale à apprendre) : ici c'est
contextuel à une conversation et un client précis.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class PendingQuestion(Base, TimestampMixin):
    __tablename__ = "pending_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    # D'où vient la question : customer (posée par le client) | jenny (info qu'il
    # manque à Jenny pour traiter) | agent.
    origin: Mapped[str] = mapped_column(
        String(20), default="customer", server_default="customer", nullable=False
    )
    # open → answered | dismissed.
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open", nullable=False, index=True
    )
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    answered_by: Mapped[str | None] = mapped_column(String(255), default=None)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
