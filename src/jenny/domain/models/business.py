"""Modèle SQLAlchemy pour les businesses (comptes utilisateurs).

Représente un freelance, une PME ou un petit commerce
qui utilise Jenny pour gérer ses messages clients.
"""

import uuid

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Business(Base, TimestampMixin):
    """Compte business (freelance, PME, commerce)."""

    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nom du business",
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        comment="Identifiant URL-friendly",
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        comment="Email principal du business",
    )
    phone: Mapped[str | None] = mapped_column(
        String(50),
        default=None,
        comment="Téléphone de contact du business",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="Description / présentation du business",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Europe/Paris",
        server_default="Europe/Paris",
        nullable=False,
        comment="Fuseau horaire (IANA) du business",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        comment="Business actif ou désactivé",
    )
    # Horaires d'ouverture : {"mon": ["09:00","19:00"], "sun": null, …} (clés en
    # anglais lun-dim). null/absent = fermé ce jour-là.
    business_hours: Mapped[dict | None] = mapped_column(JSON, default=None)
    auto_reply_message: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="Message envoyé automatiquement hors horaires d'ouverture",
    )
    sla_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default="30",
        nullable=False,
        comment="Seuil SLA par défaut : conversation en retard si en attente depuis +N min",
    )
    # Surcharges SLA fines : {"priority": {"high": 10, "low": 120},
    # "channel": {"whatsapp": 15}}. La résolution prend le min applicable ;
    # absence → sla_minutes. Permet un SLA plus strict pour les priorités hautes.
    sla_rules: Mapped[dict | None] = mapped_column(JSON, default=None)
    # « Cerveau de Jenny » : personnalité configurable (ton, curseurs, règles d'or,
    # vocabulaire). {"tone": "cool", "sliders": {...}, "rules": [...], "vocab": [...]}.
    persona: Mapped[dict | None] = mapped_column(JSON, default=None)

    # ── Acompte anti-no-show (configurable par le salon) ──
    # Demander un acompte à la réservation réduit fortement les lapins.
    deposit_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
        comment="Demander un acompte à la réservation",
    )
    deposit_percent: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default="30",
        nullable=False,
        comment="Pourcentage du prix de la prestation demandé en acompte (0-100)",
    )
    deposit_min_cents: Mapped[int] = mapped_column(
        Integer,
        default=1000,
        server_default="1000",
        nullable=False,
        comment="Acompte forfaitaire (centimes) quand le prix de la prestation est inconnu",
    )

    # ── Rappels configurables + fidélité ──
    reminder_lead_minutes: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60", nullable=False,
        comment="Délai du rappel « imminent » avant le RDV (minutes)",
    )
    day_reminder_lead_hours: Mapped[int] = mapped_column(
        Integer, default=24, server_default="24", nullable=False,
        comment="Délai du rappel « la veille » avant le RDV (heures)",
    )
    loyalty_threshold: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10", nullable=False,
        comment="Nombre de RDV honorés pour débloquer une récompense fidélité (0 = désactivé)",
    )

    # Relations
    # ⚠️ Efficacité : ces collections sont volumineuses (tous les clients, RDV,
    # commandes… d'un salon). Surtout PAS « lazy=selectin » : chaque chargement
    # d'un Business (à CHAQUE message du chat) déclencherait un SELECT par
    # collection → toute la base du salon en mémoire pour rien. Aucun code ne lit
    # ces relations via l'objet Business (les besoins réels passent par des requêtes
    # filtrées dédiées). On les laisse donc en chargement à la demande (« select »).
    customers = relationship("Customer", back_populates="business", lazy="select")
    conversations = relationship("Conversation", back_populates="business", lazy="select")
    customer_addresses = relationship(
        "CustomerAddress",
        back_populates="business",
        lazy="select",
    )
    orders = relationship("Order", back_populates="business", lazy="select")
    customer_transactions = relationship(
        "CustomerTransaction",
        back_populates="business",
        lazy="select",
    )
    customer_documents = relationship(
        "CustomerDocument",
        back_populates="business",
        lazy="select",
    )
    support_tickets = relationship(
        "SupportTicket",
        back_populates="business",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Business(id={self.id}, name={self.name})>"
