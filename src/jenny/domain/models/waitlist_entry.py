"""Liste d'attente : un client veut un créneau alors que le salon est complet.

Quand Jenny ne trouve aucun créneau pour une prestation, elle propose au client
de s'inscrire en liste d'attente. Dès qu'une annulation/déplacement libère un
créneau compatible, le premier inscrit est prévenu automatiquement. Les trous se
remplissent tout seuls.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class WaitlistEntry(Base, TimestampMixin):
    __tablename__ = "waitlist_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)

    # Prestation souhaitée (nom) + fenêtre libre (texte : « mardi matin », « cette semaine »).
    service: Mapped[str | None] = mapped_column(String(120), default=None)
    desired_window: Mapped[str | None] = mapped_column(String(200), default=None)
    # Pour recontacter un client de chat anonyme.
    customer_name: Mapped[str | None] = mapped_column(String(120), default=None)
    customer_contact: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    # waiting → notified → booked | cancelled.
    status: Mapped[str] = mapped_column(
        String(20), default="waiting", server_default="waiting", nullable=False, index=True
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
