"""Modèle SQLAlchemy pour les conversations.

Une conversation représente un fil de discussion
entre un client et un commerce sur un canal donné.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    """Conversation (fil de discussion) entre un client et un commerce."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Canal de la conversation",
    )
    external_conversation_id: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        index=True,
        comment="ID de thread externe (email In-Reply-To, wa:<sender>, ...)",
    )

    # ── Suivi ──
    status: Mapped[str] = mapped_column(
        String(30),
        default="open",
        nullable=False,
        comment="open, closed, archived, escalated",
    )
    priority_level: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
        comment="low, medium, high, critical",
    )
    current_intent: Mapped[str | None] = mapped_column(
        String(100),
        default=None,
        comment="Dernière intention détectée",
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    first_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    last_message_preview: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        comment="Aperçu du dernier message",
    )
    is_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        comment="Conseiller humain assigné (si escalade)",
    )

    # ── Contexte ──
    summary: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="Résumé de la conversation (généré par LLM)",
    )
    # Étiquettes métier libres (urgent, à relancer…). Colonne JSON : stocke une
    # liste de chaînes, portable Postgres/SQLite.
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    # Reportée (snooze) : masquée de la vue active jusqu'à cette date.
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Sentiment du dernier message client (positive/neutral/negative).
    sentiment: Mapped[str | None] = mapped_column(String(20), default=None)

    # Relations
    business = relationship("Business", back_populates="conversations")
    customer = relationship("Customer", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        lazy="selectin",
    )
    customer_documents = relationship(
        "CustomerDocument",
        back_populates="conversation",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, channel={self.channel}, "
            f"status={self.status}, messages={self.message_count})>"
        )
