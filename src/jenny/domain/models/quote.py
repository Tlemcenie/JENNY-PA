"""Devis (quote) généré par Jenny depuis le catalogue de prestations."""

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Quote(Base, TimestampMixin):
    """Un devis réel : lignes (prestations du catalogue), total, validité, statut.

    Créé par l'action ``generate_quote`` à partir des prix réels du catalogue,
    persisté, et (si email connu) envoyé au client. Le suivi est 100 % réel.
    """

    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
        nullable=True,
        index=True,
    )
    # Référence lisible (ex. DEV-1A2B3C4D).
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    # Lignes du devis : [{"name", "price_eur", "duration_minutes"}].
    items: Mapped[list | None] = mapped_column(JSON, default=None)
    # Montants : total_cents = TTC (prix catalogue). HT/TVA dérivés du taux.
    total_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_ht_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tva_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vat_rate: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    # draft → sent → accepted | expired
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    sent_to_email: Mapped[str | None] = mapped_column(String(255), default=None)
    valid_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    business = relationship("Business", lazy="selectin")
    customer = relationship("Customer", lazy="selectin")

    @property
    def total_eur(self) -> float:
        return round(self.total_cents / 100, 2)
