"""Mapping canal Meta / autre → business."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class ChannelAccount(Base, TimestampMixin):
    """Lie un compte externe (ex. phone_number_id WhatsApp) à un business."""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("channel", "external_account_id", name="uq_channel_accounts_channel_external"),
    )

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
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_account_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="phone_number_id, page_id, etc.",
    )
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)

    business = relationship("Business", backref="channel_accounts", lazy="selectin")
