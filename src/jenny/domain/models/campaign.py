"""Relances : campagnes du gérant et offres de créneaux libres."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class Campaign(Base, TimestampMixin):
    """Une relance envoyée à un segment."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # dormants | no_shows | nouveaux | fideles
    segment: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # sending | sent | failed
    status: Mapped[str] = mapped_column(
        String(20), default="sending", server_default="sending", nullable=False
    )
    target_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    sent_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # plafond, désinscrit, injoignable
    skipped_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255), default=None)


class CampaignRecipient(Base):
    """Un client touché par une campagne."""

    __tablename__ = "campaign_recipients"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # None = envoi raté
    channel: Mapped[str | None] = mapped_column(String(20), default=None)


class SlotOffer(Base, TimestampMixin):
    """Un créneau libre proposé à un client."""

    __tablename__ = "slot_offers"
    __table_args__ = (
        # jamais 2 fois le même créneau
        UniqueConstraint(
            "business_id", "recipient_key", "slot_start", name="uq_slot_offers_recipient_slot"
        ),
        Index("ix_slot_offers_business_slot", "business_id", "slot_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        default=None,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    waitlist_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    # id client ou conv:<id>
    recipient_key: Mapped[str] = mapped_column(String(80), nullable=False)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False
    )
    service: Mapped[str | None] = mapped_column(String(120), default=None)
    # waitlist | rebook
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # matin | annulation | manuel
    reason: Mapped[str] = mapped_column(
        String(20), default="matin", server_default="matin", nullable=False
    )
    # None = envoi raté
    channel: Mapped[str | None] = mapped_column(String(20), default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
