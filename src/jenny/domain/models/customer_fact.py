"""Fait durable mémorisé sur un client (mémoire long terme de Jenny).

Au fil des conversations, Jenny retient des informations stables et utiles sur
un client (préférences, contraintes, contexte récurrent) — par ex. « préfère les
rendez-vous le matin », « allergique à l'ammoniaque », « cliente fidèle depuis 2022 ».
Ces faits sont réinjectés dans le contexte des échanges suivants pour une relation
personnalisée, comme un vrai membre de l'équipe qui se souvient de ses clients.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class CustomerFact(Base, TimestampMixin):
    __tablename__ = "customer_facts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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

    # Le fait, en une phrase ("Préfère être appelé en fin d'après-midi.").
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    # Empreinte normalisée pour dédupliquer.
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # preference | contact | constraint | context | other
    kind: Mapped[str] = mapped_column(
        String(30), default="other", server_default="other", nullable=False
    )
    # conversation (extrait auto) | manual (saisi par l'équipe).
    source: Mapped[str] = mapped_column(
        String(20), default="conversation", server_default="conversation", nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None
    )
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0, server_default="1.0", nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
