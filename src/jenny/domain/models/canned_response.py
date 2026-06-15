"""Réponses enregistrées : modèles de réponse réutilisables par les agents."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class CannedResponse(Base, TimestampMixin):
    """Réponse pré-rédigée réutilisable, rattachée à un business.

    ``shortcut`` est un raccourci optionnel (ex. ``horaires``) que l'agent peut
    taper pour insérer rapidement le contenu.
    """

    __tablename__ = "canned_responses"

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
    shortcut: Mapped[str | None] = mapped_column(String(60), default=None)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<CannedResponse(id={self.id}, title={self.title})>"
