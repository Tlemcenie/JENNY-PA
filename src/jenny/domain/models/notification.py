"""Notifications destinées aux agents (cloche du dashboard).

Une notification est créée lorsqu'un événement requiert l'attention d'un membre
de l'équipe : conversation attribuée, escalade automatique, snooze échu… Le
frontend les liste dans le centre de notifications (cloche) et les pousse en
temps réel via le bus SSE.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

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
    # Destinataire : email de l'agent ciblé, ou None = visible par toute l'équipe.
    recipient: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    # Type d'événement : assigned, escalated, snooze_due, mention, system…
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, default=None)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    meta: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Date de lecture (None = non lue).
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default="now()",
        nullable=False,
        index=True,
    )

    business = relationship("Business", lazy="selectin")
