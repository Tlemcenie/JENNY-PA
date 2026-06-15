"""Rendez-vous / créneaux du calendrier (onglet Calendrier).

Un rendez-vous est un événement daté rattaché à un business (et éventuellement à
un client / une conversation). Alimente l'onglet Calendrier façon Google Agenda
et peut être créé par l'agent de planification de Jenny ou manuellement.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    # Index composites pour les requêtes chaudes (à l'échelle = beaucoup de RDV) :
    # disponibilités/agenda/stats/rappels filtrent (business_id + plage start_at) ;
    # historique client + anti-doublon filtrent (business_id + customer_id) ;
    # stats/no-show filtrent (business_id + status).
    __table_args__ = (
        Index("ix_appointments_business_start", "business_id", "start_at"),
        Index("ix_appointments_business_customer", "business_id", "customer_id"),
        Index("ix_appointments_business_status", "business_id", "status"),
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
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        default=None,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    # Canal d'origine (whatsapp, instagram, email, form, manual…).
    channel: Mapped[str | None] = mapped_column(String(50), default=None)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # scheduled, confirmed, cancelled, completed
    status: Mapped[str] = mapped_column(
        String(20), default="scheduled", nullable=False
    )
    # Email de l'agent / source ayant créé le RDV (Jenny ou un humain).
    created_by: Mapped[str | None] = mapped_column(String(255), default=None)
    # Date d'envoi du rappel « dans l'heure » (None = pas encore) — anti-doublon.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Date d'envoi du rappel « la veille » (RDV dans les 24h) — anti-doublon.
    day_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # ── Suivi post-RDV (fidélisation) ──
    # Demande d'avis envoyée après la prestation (anti-doublon).
    review_request_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Relance « il est temps de reprendre RDV » envoyée (anti-doublon).
    rebook_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # ── Acompte (anti-no-show) ──
    # Montant demandé (centimes), statut du paiement, et lien vers le PaymentRecord.
    deposit_cents: Mapped[int | None] = mapped_column(Integer, default=None)
    # none | pending | paid | waived
    deposit_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none", nullable=False
    )
    deposit_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        default=None,
    )

    # Notes techniques internes (formule couleur, allergies…) — jamais montrées au client.
    staff_notes: Mapped[str | None] = mapped_column(Text, default=None)

    business = relationship("Business", lazy="selectin")
    customer = relationship("Customer", lazy="selectin")
