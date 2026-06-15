"""Modèle SQLAlchemy pour les événements de message.

Trace chaque étape du cycle de vie d'un message :
ingestion, normalisation, classification, génération de réponse,
envoi, erreur. Utile pour le debug, l'observabilité et l'évaluation ML.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base


class MessageEvent(Base):
    """Événement sur un message (audit trail)."""

    __tablename__ = "message_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "Type : ingested, normalized, classified, reply_generated, reply_sent, escalated, error"
        ),
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="success",
        nullable=False,
        comment="success, failure, skipped",
    )
    detail: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="Détails ou message d'erreur",
    )
    payload: Mapped[dict | None] = mapped_column(
        JSON,
        default=None,
        comment="Données associées à l'événement",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        server_default="now()",
    )

    def __repr__(self) -> str:
        return (
            f"<MessageEvent(id={self.id}, message_id={self.message_id}, "
            f"type={self.event_type}, status={self.status})>"
        )
