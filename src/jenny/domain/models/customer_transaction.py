"""Transactions financières (table de fait)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class CustomerTransaction(Base, TimestampMixin):
    """Un mouvement monétaire (paiement, remboursement, etc.)."""

    __tablename__ = "customer_transactions"

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
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    transaction_type_id: Mapped[int] = mapped_column(
        ForeignKey("transaction_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40), default=None)
    external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, default=None)

    business = relationship("Business", back_populates="customer_transactions")
    customer = relationship("Customer", back_populates="transactions")
    order = relationship("Order", back_populates="transactions")
    transaction_type = relationship(
        "TransactionType",
        back_populates="transactions",
    )

    def __repr__(self) -> str:
        return f"<CustomerTransaction(id={self.id}, amount_minor={self.amount_minor})>"
