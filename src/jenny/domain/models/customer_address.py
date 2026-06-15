"""Adresses postales rattachées aux clients."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class CustomerAddress(Base, TimestampMixin):
    """Adresse (facturation, livraison, etc.) pour un client."""

    __tablename__ = "customer_addresses"

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str | None] = mapped_column(String(100), default=None)
    line1: Mapped[str] = mapped_column(String(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(255), default=None)
    city: Mapped[str | None] = mapped_column(String(120), default=None)
    region: Mapped[str | None] = mapped_column(String(120), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(32), default=None)
    country: Mapped[str | None] = mapped_column(String(2), default=None)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    business = relationship("Business", back_populates="customer_addresses")
    customer = relationship("Customer", back_populates="addresses")

    def __repr__(self) -> str:
        return f"<CustomerAddress(id={self.id}, customer_id={self.customer_id})>"
