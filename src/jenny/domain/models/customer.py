"""Modèle SQLAlchemy pour les profils clients.

Un CustomerProfile centralise les informations d'un client
à travers tous les canaux, rattaché à un business.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    """Profil client multicanal."""

    __tablename__ = "customers"

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

    # ── Identité ──
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), default=None, index=True)
    instagram_handle: Mapped[str | None] = mapped_column(String(100), default=None)
    messenger_id: Mapped[str | None] = mapped_column(String(255), default=None)

    # ── Metadata ──
    # ARRAY natif sur Postgres ; JSON en repli sur SQLite (tests) où le type
    # ARRAY ne sait pas lier une liste Python. Sans effet sur la prod Postgres.
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String).with_variant(JSON(), "sqlite"),
        default=None,
        comment="Tags métier libres",
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    # ── Suivi ──
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # RGPD : date d'anonymisation (droit à l'effacement). None = données actives.
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Relations
    business = relationship("Business", back_populates="customers")
    conversations = relationship("Conversation", back_populates="customer", lazy="selectin")
    addresses = relationship(
        "CustomerAddress",
        back_populates="customer",
        lazy="selectin",
    )
    orders = relationship("Order", back_populates="customer", lazy="selectin")
    transactions = relationship(
        "CustomerTransaction",
        back_populates="customer",
        lazy="selectin",
    )
    documents = relationship(
        "CustomerDocument",
        back_populates="customer",
        lazy="selectin",
    )
    support_tickets = relationship(
        "SupportTicket",
        back_populates="customer",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        display = self.full_name or self.email or self.phone or str(self.id)[:8]
        return f"<Customer(id={self.id}, display={display})>"
