"""Schémas Pydantic du domaine Jenny."""

from jenny.domain.schemas.conversation import ConversationRead, ConversationUpdate
from jenny.domain.schemas.customer import CustomerProfileCreate, CustomerProfileRead
from jenny.domain.schemas.message import (
    MessageCreate,
    MessageIn,
    MessageNormalized,
    MessageResponse,
)

__all__ = [
    "ConversationRead",
    "ConversationUpdate",
    "CustomerProfileCreate",
    "CustomerProfileRead",
    "MessageCreate",
    "MessageIn",
    "MessageNormalized",
    "MessageResponse",
]
