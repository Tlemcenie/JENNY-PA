"""Catalogue de prestations d'un business (coiffure & co.).

Le commerçant décrit ses prestations (nom, catégorie, durée, prix). Jenny s'en
sert pour répondre aux tarifs SANS rien inventer, calculer la durée d'un
rendez-vous, et proposer/réserver le bon créneau. C'est la source de vérité
métier pour les prix et la durée des RDV.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class Prestation(Base, TimestampMixin):
    __tablename__ = "prestations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # coupe | couleur | coiffage | soin | barbe | autre (libre).
    category: Mapped[str] = mapped_column(
        String(40), default="autre", server_default="autre", nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False
    )
    # Prix en centimes d'euro (entier, évite les imprécisions de flottant).
    price_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    @property
    def price_eur(self) -> float:
        return round(self.price_cents / 100, 2)
