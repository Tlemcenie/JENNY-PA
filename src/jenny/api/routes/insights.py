"""Tableau de bord / Analytics.

Agrège des statistiques réelles depuis la base pour le business de
l'utilisateur courant : conversations, messages, clients, commandes,
base de connaissances, répartition par canal, intentions principales et
volume de messages sur les 7 derniers jours.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.order import Order
from jenny.rag.knowledge_base import KnowledgeBase

logger = get_logger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"])


class ChannelStat(BaseModel):
    channel: str
    count: int


class AgentStat(BaseModel):
    agent: str
    count: int


class IntentStat(BaseModel):
    intent: str
    count: int


class DailyStat(BaseModel):
    date: str
    count: int


class InsightsResponse(BaseModel):
    """Statistiques agrégées du business."""

    business_id: str | None
    conversations_total: int
    conversations_open: int
    conversations_escalated: int
    messages_total: int
    messages_inbound: int
    messages_outbound: int
    customers_total: int
    orders_total: int
    revenue_minor: int
    currency: str
    knowledge_entries: int
    escalation_rate: float
    avg_messages_per_conversation: float
    avg_first_response_minutes: float | None = None
    by_channel: list[ChannelStat]
    by_agent: list[AgentStat] = []
    top_intents: list[IntentStat]
    messages_last_7_days: list[DailyStat]


def _empty(business_id: str | None) -> InsightsResponse:
    return InsightsResponse(
        business_id=business_id,
        conversations_total=0,
        conversations_open=0,
        conversations_escalated=0,
        messages_total=0,
        messages_inbound=0,
        messages_outbound=0,
        customers_total=0,
        orders_total=0,
        revenue_minor=0,
        currency="EUR",
        knowledge_entries=0,
        escalation_rate=0.0,
        avg_messages_per_conversation=0.0,
        by_channel=[],
        top_intents=[],
        messages_last_7_days=[],
    )


@router.get("", response_model=InsightsResponse)
async def get_insights(
    db: DbSession,
    principal: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> InsightsResponse:
    """Agrège les statistiques du business de l'utilisateur courant.

    ``days`` contrôle la fenêtre du graphe de volume (7 ou 30 jours typiquement).
    """
    bid = principal.business_id
    if bid is None:
        return _empty(None)

    # ── Conversations ──
    conv_total, conv_open, conv_escalated = (
        await db.execute(
            select(
                func.count(Conversation.id),
                func.count(Conversation.id).filter(Conversation.status == "open"),
                func.count(Conversation.id).filter(Conversation.is_escalated.is_(True)),
            ).where(Conversation.business_id == bid)
        )
    ).one()

    # ── Messages (total + par direction) ──
    msg_total, msg_in, msg_out = (
        await db.execute(
            select(
                func.count(Message.id),
                func.count(Message.id).filter(Message.direction == "inbound"),
                func.count(Message.id).filter(Message.direction == "outbound"),
            ).where(Message.business_id == bid)
        )
    ).one()

    # ── Clients ──
    customers_total = (
        await db.execute(
            select(func.count(Customer.id)).where(Customer.business_id == bid)
        )
    ).scalar_one()

    # ── Commandes + chiffre d'affaires (commandes payées) ──
    orders_total, revenue_minor = (
        await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(
                    func.sum(Order.total_amount_minor).filter(Order.status == "paid"),
                    0,
                ),
            ).where(Order.business_id == bid)
        )
    ).one()

    # ── Répartition par canal ──
    channel_rows = (
        await db.execute(
            select(Conversation.channel, func.count(Conversation.id))
            .where(Conversation.business_id == bid)
            .group_by(Conversation.channel)
            .order_by(func.count(Conversation.id).desc())
        )
    ).all()
    by_channel = [ChannelStat(channel=c or "inconnu", count=n) for c, n in channel_rows]

    # ── Intentions principales ──
    intent_rows = (
        await db.execute(
            select(Conversation.current_intent, func.count(Conversation.id))
            .where(
                Conversation.business_id == bid,
                Conversation.current_intent.is_not(None),
            )
            .group_by(Conversation.current_intent)
            .order_by(func.count(Conversation.id).desc())
            .limit(5)
        )
    ).all()
    top_intents = [IntentStat(intent=i, count=n) for i, n in intent_rows if i]

    # ── Répartition par agent (messages sortants par expéditeur) ──
    agent_rows = (
        await db.execute(
            select(Message.sender_name, func.count(Message.id))
            .where(
                Message.business_id == bid,
                Message.direction == "outbound",
                Message.sender_name.is_not(None),
            )
            .group_by(Message.sender_name)
            .order_by(func.count(Message.id).desc())
            .limit(10)
        )
    ).all()
    by_agent = [AgentStat(agent=a or "—", count=n) for a, n in agent_rows if a]

    # ── Volume de messages sur la fenêtre demandée (days) ──
    today = datetime.now(UTC).date()
    since = datetime.now(UTC) - timedelta(days=days - 1)
    day_rows = (
        await db.execute(
            select(func.date(Message.created_at), func.count(Message.id))
            .where(Message.business_id == bid, Message.created_at >= since)
            .group_by(func.date(Message.created_at))
        )
    ).all()
    counts_by_day = {str(d): n for d, n in day_rows}
    messages_last_7_days = [
        DailyStat(
            date=str(today - timedelta(days=offset)),
            count=counts_by_day.get(str(today - timedelta(days=offset)), 0),
        )
        for offset in range(days - 1, -1, -1)
    ]

    # ── Base de connaissances ──
    knowledge_entries = 0
    try:
        kb_stats = await KnowledgeBase(business_id=bid, session=db).stats()
        knowledge_entries = int(kb_stats.get("total_entries", 0))
    except Exception as exc:
        logger.warning("insights.knowledge_stats_failed", error=str(exc))

    escalation_rate = round(conv_escalated / conv_total, 4) if conv_total else 0.0
    avg_msgs = round(msg_total / conv_total, 2) if conv_total else 0.0

    # ── Temps de 1ʳᵉ réponse moyen (entre 1er message client et 1ʳᵉ réponse) ──
    # Calculé en Python pour rester portable Postgres/SQLite (pas d'EXTRACT EPOCH).
    fr_rows = (
        await db.execute(
            select(
                Message.conversation_id,
                func.min(
                    case((Message.direction == "inbound", Message.created_at))
                ).label("first_in"),
                func.min(
                    case((Message.direction == "outbound", Message.created_at))
                ).label("first_out"),
            )
            .where(Message.business_id == bid)
            .group_by(Message.conversation_id)
        )
    ).all()
    diffs = [
        (fo - fi).total_seconds() / 60
        for _cid, fi, fo in fr_rows
        if fi is not None and fo is not None and fo >= fi
    ]
    avg_first_response = round(sum(diffs) / len(diffs), 1) if diffs else None

    return InsightsResponse(
        business_id=str(bid),
        conversations_total=conv_total,
        conversations_open=conv_open,
        conversations_escalated=conv_escalated,
        messages_total=msg_total,
        messages_inbound=msg_in,
        messages_outbound=msg_out,
        customers_total=customers_total,
        orders_total=orders_total,
        revenue_minor=int(revenue_minor or 0),
        currency="EUR",
        knowledge_entries=knowledge_entries,
        escalation_rate=escalation_rate,
        avg_messages_per_conversation=avg_msgs,
        avg_first_response_minutes=avg_first_response,
        by_channel=by_channel,
        by_agent=by_agent,
        top_intents=top_intents,
        messages_last_7_days=messages_last_7_days,
    )
