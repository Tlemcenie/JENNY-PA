"""Documents clients stockés ou référencés (hors chunks RAG)."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jenny.db.base import Base, TimestampMixin


class CustomerDocument(Base, TimestampMixin):
    """Métadonnées d'un fichier lié à un client (facture uploadée, etc.)."""

    __tablename__ = "customer_documents"

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_categories.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(500), default=None)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, default=None)

    business = relationship("Business", back_populates="customer_documents")
    customer = relationship("Customer", back_populates="documents")
    category = relationship("DocumentCategory", back_populates="documents")
    conversation = relationship("Conversation", back_populates="customer_documents")
    message = relationship("Message", back_populates="customer_documents")

    def __repr__(self) -> str:
        return f"<CustomerDocument(id={self.id}, file_name={self.file_name})>"
