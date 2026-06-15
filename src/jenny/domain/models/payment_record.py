"""Paiement Stripe / PayPal persisté."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class PaymentRecord(Base, TimestampMixin):
    __tablename__ = "payments"

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
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger(), default=None)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    order_reference: Mapped[str | None] = mapped_column(String(120), default=None)
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, default=None)

    business = relationship("Business", backref="payments", lazy="selectin")
