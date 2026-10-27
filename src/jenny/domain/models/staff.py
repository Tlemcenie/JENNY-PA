"""Coiffeurs du salon (un fauteuil chacun)."""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jenny.db.base import Base, TimestampMixin


class Staff(Base, TimestampMixin):
    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # couleur agenda (#rrggbb)
    color: Mapped[str | None] = mapped_column(String(20), default=None)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # même format que business_hours, null = horaires du salon
    working_hours: Mapped[dict | None] = mapped_column(JSON, default=None)
    # false = seulement ses compétences
    all_services: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )


class StaffSkill(Base):
    """Prestation qu'un coiffeur sait faire."""

    __tablename__ = "staff_skills"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prestations.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
