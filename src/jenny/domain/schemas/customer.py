"""Schémas Pydantic v2 pour les profils clients.

Un CustomerProfile centralise les informations d'un client
à travers tous les canaux, évitant la duplication.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class CustomerProfileRead(BaseModel):
    """Vue lecture d'un profil client."""

    id: UUID
    business_id: UUID

    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    instagram_handle: str | None = None
    messenger_id: str | None = None

    tags: list[str] = []
    notes: str | None = None

    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    conversation_count: int = 0

    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomerProfileCreate(BaseModel):
    """Payload de création d'un profil client (minimal)."""

    business_id: UUID
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    instagram_handle: str | None = None
    messenger_id: str | None = None
