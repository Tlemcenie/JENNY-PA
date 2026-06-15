"""Journal d'audit : trace immuable de « qui a fait quoi » sur le business.

Chaque action sensible côté dashboard (changement de statut, attribution,
étiquetage, réponse, fusion, révocation de clé API…) écrit une ligne ici. Sert
à la conformité, au support et à la timeline d'activité de l'équipe.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

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
    # Auteur de l'action : email de l'agent, ou None pour une action système
    # (auto-escalade, dé-snooze automatique…).
    actor: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    # Verbe machine, ex. "conversation.status_changed", "api_key.revoked".
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    # Phrase lisible par un humain (« A clôturé la conversation »).
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Contexte structuré optionnel (avant/après, valeurs…).
    meta: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default="now()",
        nullable=False,
        index=True,
    )

    business = relationship("Business", lazy="selectin")
