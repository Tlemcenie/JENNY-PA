"""Commandes (fait métier)."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    """Commande ou panier validé, rattachée à un client et un business."""

    __tablename__ = "orders"

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
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    total_amount_minor: Mapped[int | None] = mapped_column(BigInteger, default=None)
    tax_amount_minor: Mapped[int | None] = mapped_column(BigInteger, default=None)
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, default=None)

    business = relationship("Business", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    transactions = relationship(
        "CustomerTransaction",
        back_populates="order",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, reference={self.reference}, status={self.status})>"
