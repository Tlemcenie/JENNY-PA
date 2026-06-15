"""Idempotence des webhooks externes."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base


class WebhookDelivery(Base):
    """Empreinte d'une livraison webhook déjà traitée (Meta, Stripe...)."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dedup_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("now()"),
        nullable=False,
    )
