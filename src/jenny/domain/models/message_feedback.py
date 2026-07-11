"""Feedback utilisateur sur une réponse de Jenny (pouce ↑ / pouce ↓).

Un moyen simple pour l'utilisateur de valider (ou non) une réponse générée par
Jenny. Une seule évaluation par message (modifiable) — clé unique sur
``message_id``. Alimente les métriques de satisfaction des réponses.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class MessageFeedback(Base, TimestampMixin):
    """Évaluation 👍/👎 d'un message sortant (réponse de Jenny)."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_message_feedback_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # +1 = pouce en haut (utile) ; -1 = pouce en bas (à revoir).
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    # Commentaire libre facultatif (ex. « n'a pas répondu à ma question »).
    comment: Mapped[str | None] = mapped_column(Text, default=None)
