"""Fermetures exceptionnelles d'un salon (congés, jours fériés, absences).

Au-delà des horaires hebdomadaires (``business.business_hours``), un salon peut
fermer ponctuellement. Le moteur de disponibilité exclut ces jours : Jenny ne
propose ni ne réserve de créneau dessus.
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class BusinessClosure(Base, TimestampMixin):
    __tablename__ = "business_closures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plage fermée, bornes incluses (un seul jour → start == end).
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), default=None)
