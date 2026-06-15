"""Schémas Pydantic v2 pour les conversations.

Une conversation regroupe les échanges entre un client
et un business sur un canal donné.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from jenny.domain.schemas.message import ChannelType

PriorityLevel = Literal["low", "medium", "high", "critical"]
ConversationStatus = Literal["open", "pending", "closed", "escalated"]


class ConversationRead(BaseModel):
    """Vue lecture d'une conversation."""

    id: UUID
    business_id: UUID
    customer_id: UUID | None = None

    channel: ChannelType
    external_conversation_id: str | None = None

    status: ConversationStatus = "open"
    priority_level: PriorityLevel = "medium"

    first_message_at: datetime
    last_message_at: datetime
    last_message_preview: str | None = None

    message_count: int = 0
    detected_topic: str | None = None
    assigned_to: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationUpdate(BaseModel):
    """Payload de mise à jour d'une conversation."""

    status: ConversationStatus | None = None
    priority_level: PriorityLevel | None = None
    assigned_to: str | None = None
    detected_topic: str | None = None
