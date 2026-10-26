"""Recherche globale (palette de commandes ⌘K).

Agrège, en une requête rapide et scopée au business, les résultats les plus
pertinents parmi les conversations, les clients et les rendez-vous. Conçu pour
alimenter la palette de recherche du dashboard (réponses < 100 ms typiquement).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message

router = APIRouter(prefix="/search", tags=["Search"])


class SearchConversation(BaseModel):
    id: str
    customer_name: str | None = None
    channel: str
    preview: str | None = None


class SearchCustomer(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None


class SearchAppointment(BaseModel):
    id: str
    title: str
    start_at: datetime


class GlobalSearchResponse(BaseModel):
    query: str
    conversations: list[SearchConversation]
    customers: list[SearchCustomer]
    appointments: list[SearchAppointment]


@router.get("", response_model=GlobalSearchResponse)
async def global_search(
    db: DbSession,
    principal: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> GlobalSearchResponse:
    """Recherche transversale (conversations, clients, rendez-vous)."""
    bid = principal.business_id
    if bid is None:
        return GlobalSearchResponse(query=q, conversations=[], customers=[], appointments=[])
    pattern = f"%{q.strip()}%"

    # Conversations : nom du client OU contenu d'un message.
    conv_by_customer = select(Customer.id).where(
        Customer.business_id == bid, Customer.full_name.ilike(pattern)
    )
    conv_by_msg = select(Message.conversation_id).where(
        Message.business_id == bid, Message.content_text.ilike(pattern)
    )
    # colonnes utiles seulement
    conv_rows = (
        await db.execute(
            select(
                Conversation.id,
                Conversation.channel,
                Conversation.last_message_preview,
                Customer.full_name,
            )
            .outerjoin(Customer, Conversation.customer_id == Customer.id)
            .where(
                Conversation.business_id == bid,
                or_(
                    Conversation.customer_id.in_(conv_by_customer),
                    Conversation.id.in_(conv_by_msg),
                    cast(Conversation.tags, String).ilike(pattern),
                ),
            )
            .order_by(
                func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
            )
            .limit(limit)
        )
    ).all()
    conversations = [
        SearchConversation(id=str(cid), customer_name=name, channel=channel, preview=preview)
        for cid, channel, preview, name in conv_rows
    ]

    cust_rows = (
        await db.execute(
            select(Customer.id, Customer.full_name, Customer.email)
            .where(
                Customer.business_id == bid,
                or_(
                    Customer.full_name.ilike(pattern),
                    Customer.email.ilike(pattern),
                    Customer.phone.ilike(pattern),
                ),
            )
            .limit(limit)
        )
    ).all()
    customers = [
        SearchCustomer(id=str(cid), full_name=name, email=email) for cid, name, email in cust_rows
    ]

    appt_rows = (
        await db.execute(
            select(Appointment.id, Appointment.title, Appointment.start_at)
            .where(
                Appointment.business_id == bid,
                or_(
                    Appointment.title.ilike(pattern),
                    Appointment.location.ilike(pattern),
                ),
            )
            .order_by(Appointment.start_at.desc())
            .limit(limit)
        )
    ).all()
    appointments = [
        SearchAppointment(id=str(aid), title=title, start_at=start)
        for aid, title, start in appt_rows
    ]

    return GlobalSearchResponse(
        query=q, conversations=conversations, customers=customers, appointments=appointments
    )
