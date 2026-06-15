"""Dimension : types de mouvement financier."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base


class TransactionType(Base):
    """Référentiel paiement, remboursement, etc."""

    __tablename__ = "transaction_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    transactions = relationship(
        "CustomerTransaction",
        back_populates="transaction_type",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<TransactionType(code={self.code})>"
