"""Utilisateur humain (OAuth Google, futur dashboard)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from jenny.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)

    # Super-administrateur plateforme : accès à la console d'admin (toutes les
    # entreprises, tous les comptes). Distinct des rôles par-business.
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=expression.false()
    )

    # ── Vérification d'email (code à 6 chiffres envoyé à l'inscription) ──
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=expression.false()
    )
    email_verification_code_hash: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
    email_verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    email_verification_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # ── Réinitialisation de mot de passe (code à 6 chiffres) ──
    password_reset_code_hash: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    memberships = relationship(
        "BusinessMember",
        back_populates="user",
        lazy="selectin",
    )
