"""Tickets support légers en base."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class SupportTicket(Base, TimestampMixin):
    """Ticket de support lié à un business (et optionnellement un client)."""

    __tablename__ = "support_tickets"

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
    reference: Mapped[str | None] = mapped_column(String(120), default=None)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, default=None)

    business = relationship("Business", back_populates="support_tickets")
    customer = relationship("Customer", back_populates="support_tickets")

    def __repr__(self) -> str:
        return f"<SupportTicket(id={self.id}, reference={self.reference})>"
