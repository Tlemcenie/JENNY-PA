"""Lacune de connaissance : une question client à laquelle Jenny n'a pas su répondre.

Quand Jenny ne trouve aucune information fiable pour répondre (base de
connaissances vide ou non pertinente) sur une intention de type « question »,
le moteur enregistre une ``KnowledgeGap``. Le propriétaire du business voit
ensuite la liste des questions sans réponse, y répond, et peut **enregistrer**
sa réponse dans la base de connaissances — Jenny saura répondre la prochaine fois.

C'est la boucle d'apprentissage : les vraies questions des clients alimentent
la base de connaissances du commerçant.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class KnowledgeGap(Base, TimestampMixin):
    __tablename__ = "knowledge_gaps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)

    # La question (nettoyée) à laquelle Jenny n'a pas su répondre.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Empreinte normalisée pour dédupliquer les questions équivalentes.
    question_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel: Mapped[str | None] = mapped_column(String(50), default=None)
    intent: Mapped[str | None] = mapped_column(String(50), default=None)

    # open → answered → (saved_to_kb) ; ou dismissed.
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open", nullable=False, index=True
    )
    # Nombre de fois où une question équivalente a été posée (priorisation).
    occurrences: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )

    answer: Mapped[str | None] = mapped_column(Text, default=None)
    answered_by: Mapped[str | None] = mapped_column(String(255), default=None)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    saved_to_kb: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Référence (knowledge_id) de l'entrée KB créée à partir de la réponse.
    knowledge_entry_id: Mapped[str | None] = mapped_column(String(64), default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
