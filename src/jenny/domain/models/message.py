"""Modèle SQLAlchemy pour les messages clients.

Représente un message reçu ou envoyé sur n'importe quel canal.
Enrichi avec les champs canoniques pour supporter la normalisation,
la déduplication et le scoring ML.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    """Message client (entrant ou sortant)."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    )

    # ── Identification ──
    external_message_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        comment="ID unique côté canal source (pour déduplication)",
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Canal : instagram, whatsapp, messenger, email, form",
    )
    direction: Mapped[str] = mapped_column(
        String(10),
        default="inbound",
        nullable=False,
        comment="inbound ou outbound",
    )

    # ── Expéditeur ──
    sender_name: Mapped[str | None] = mapped_column(String(255), default=None)
    sender_email: Mapped[str | None] = mapped_column(String(255), default=None)
    sender_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    sender_handle: Mapped[str | None] = mapped_column(String(100), default=None)

    # ── Contenu ──
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    content_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Contenu texte brut du message",
    )
    content_html: Mapped[str | None] = mapped_column(Text, default=None)
    cleaned_text: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="Texte nettoyé (post-normalisation)",
    )
    language: Mapped[str | None] = mapped_column(
        String(10),
        default=None,
        comment="Langue détectée (ISO 639-1)",
    )

    # ── Pièces jointes ──
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    attachments_meta: Mapped[dict | None] = mapped_column(JSON, default=None)

    # ── Statut & traitement ──
    status: Mapped[str] = mapped_column(
        String(30),
        default="received",
        nullable=False,
        comment="received, normalizing, normalized, processing, responded, archived",
    )

    # ── Signaux ML (remplis progressivement) ──
    priority: Mapped[int | None] = mapped_column(
        Integer,
        default=None,
        comment="Score de priorité (1-10, calculé par ML)",
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        default=None,
        comment="Catégorie détectée (ML)",
    )
    intent_label: Mapped[str | None] = mapped_column(
        String(100),
        default=None,
        comment="Intent détecté (ML)",
    )
    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        default=None,
        comment="Score de sentiment (-1.0 à 1.0)",
    )
    urgency_flag: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Urgence détectée",
    )

    # ── Timestamps source ──
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="Timestamp original côté canal source",
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="Timestamp de réception par Jenny",
    )
    normalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="Timestamp de normalisation",
    )

    # ── Metadata brut ──
    raw_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        default=None,
        comment="Payload brut original du connecteur",
    )

    # Relations
    conversation = relationship("Conversation", back_populates="messages")
    customer_documents = relationship(
        "CustomerDocument",
        back_populates="message",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Message(id={self.id}, channel={self.channel}, "
            f"direction={self.direction}, status={self.status})>"
        )
