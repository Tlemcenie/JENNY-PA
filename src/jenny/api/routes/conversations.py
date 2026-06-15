"""Liste et détail des conversations (historique).

Endpoints de consultation, scopés au business du JWT :
- ``GET /conversations`` : liste paginée avec aperçu du dernier message.
- ``GET /conversations/{id}`` : détail avec tous les messages ordonnés.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, text, update

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.connectors.reply_dispatch import send_channel_reply
from jenny.core.events import publish_conversation_event, publish_notification_event
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import get_engine
from jenny.services.audit_service import record_audit
from jenny.services.notification_service import build_notification
from jenny.services.persona_loader import load_business_persona

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["Conversations"])

# Seuil SLA par défaut : une conversation en attente de réponse depuis plus de N
# minutes est considérée « en retard ». Surchargeable par business (sla_minutes)
# et affinable par priorité/canal (sla_rules) — voir resolve_sla_minutes.
SLA_RESPONSE_MINUTES = 30

# Ordre de tri des priorités (plus haut = plus urgent), pour le tri serveur.
PRIORITY_RANK: dict[str, int] = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def resolve_sla_minutes(
    biz: Business | None,
    *,
    priority: str | None = None,
    channel: str | None = None,
) -> int:
    """Seuil SLA effectif pour une conversation (#7).

    Part du ``sla_minutes`` du business (ou défaut), puis applique la surcharge
    la plus stricte (min) parmi celles définies dans ``sla_rules`` pour la
    priorité et le canal concernés. Permet d'exiger une réponse plus rapide sur
    les conversations critiques ou un canal donné.
    """
    base = biz.sla_minutes if biz and biz.sla_minutes else SLA_RESPONSE_MINUTES
    rules = (biz.sla_rules if biz else None) or {}
    candidates = [base]
    by_priority = rules.get("priority") or {}
    if priority and isinstance(by_priority, dict) and by_priority.get(priority):
        candidates.append(int(by_priority[priority]))
    by_channel = rules.get("channel") or {}
    if channel and isinstance(by_channel, dict) and by_channel.get(channel):
        candidates.append(int(by_channel[channel]))
    return max(1, min(candidates))


def _waiting_minutes(last_message_at: datetime | None, now: datetime) -> int | None:
    """Minutes écoulées depuis le dernier message (None si inconnu)."""
    if last_message_at is None:
        return None
    lma = last_message_at if last_message_at.tzinfo else last_message_at.replace(tzinfo=UTC)
    return max(0, int((now - lma).total_seconds() // 60))


class ConversationSummary(BaseModel):
    id: str
    channel: str
    status: str
    priority_level: str = "medium"
    current_intent: str | None = None
    message_count: int
    is_escalated: bool
    last_message_at: datetime | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    last_message_preview: str | None = None
    awaiting_reply: bool = False
    overdue: bool = False
    waiting_minutes: int | None = None
    sentiment: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class ConversationMessage(BaseModel):
    id: str
    direction: str
    sender_name: str | None = None
    content: str
    channel: str
    status: str
    attachment_count: int = 0
    created_at: datetime


class ConversationDetail(BaseModel):
    id: str
    channel: str
    status: str
    priority_level: str = "medium"
    current_intent: str | None = None
    message_count: int
    is_escalated: bool
    last_message_at: datetime | None = None
    summary: str | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    assigned_to: str | None = None
    sentiment: str | None = None
    snoozed_until: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    messages: list[ConversationMessage]


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    db: DbSession,
    principal: CurrentUser,
    status: str | None = None,
    channel: str | None = None,
    search: str | None = None,
    assigned_to: str | None = None,
    tag: str | None = None,
    priority: str | None = None,
    sort_by: Literal["recent", "oldest", "priority"] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationListResponse:
    """Liste les conversations du business (les plus récentes d'abord).

    ``search`` filtre côté serveur sur le nom du client OU le contenu d'un
    message (recherche sur TOUTES les conversations, pas seulement la page).
    ``priority`` filtre par niveau ; ``sort_by`` trie par récence ou priorité.
    """
    bid = principal.business_id
    if bid is None:
        return ConversationListResponse(conversations=[], total=0, limit=limit, offset=offset)

    biz = await db.get(Business, bid)
    now = datetime.now(UTC)

    filters = [Conversation.business_id == bid]
    if status:
        filters.append(Conversation.status == status)
    else:
        # Vue par défaut (« Tous ») = conversations actives : on masque les
        # archivées et les reportées (snooze) tant qu'elles ne sont pas dues.
        filters.append(Conversation.status != "archived")
        filters.append(
            or_(Conversation.snoozed_until.is_(None), Conversation.snoozed_until <= now)
        )
    if channel:
        filters.append(Conversation.channel == channel)
    if priority and priority.strip():
        filters.append(Conversation.priority_level == priority.strip())
    if assigned_to:
        # "me" → conversations attribuées à l'utilisateur courant.
        who = principal.email if assigned_to == "me" else assigned_to
        filters.append(Conversation.assigned_to == who)
    if tag and tag.strip():
        # tags est une colonne JSON (liste sérialisée) : on filtre sur la
        # présence du tag exact, entre guillemets, dans le JSON textuel.
        # Portable Postgres/SQLite (pas d'opérateur ARRAY natif requis).
        filters.append(cast(Conversation.tags, String).ilike(f'%"{tag.strip()}"%'))
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        customer_match = select(Customer.id).where(
            Customer.business_id == bid, Customer.full_name.ilike(pattern)
        )
        message_match = select(Message.conversation_id).where(
            Message.business_id == bid, Message.content_text.ilike(pattern)
        )
        filters.append(
            or_(
                Conversation.customer_id.in_(customer_match),
                Conversation.id.in_(message_match),
            )
        )

    total = (
        await db.execute(select(func.count(Conversation.id)).where(*filters))
    ).scalar_one()

    recency = func.coalesce(Conversation.last_message_at, Conversation.created_at)
    if sort_by == "oldest":
        order_by = [recency.asc()]
    elif sort_by == "priority":
        # Tri par urgence décroissante (critical → low), puis par récence.
        from sqlalchemy import case

        rank = case(PRIORITY_RANK, value=Conversation.priority_level, else_=1)
        order_by = [rank.desc(), recency.desc()]
    else:  # "recent"
        order_by = [recency.desc()]

    rows = (
        await db.execute(
            select(Conversation, Customer.full_name)
            .outerjoin(Customer, Conversation.customer_id == Customer.id)
            .where(*filters)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    conv_ids = [conv.id for conv, _ in rows]
    previews: dict[UUID, str] = {}
    # Direction du dernier message de chaque conversation : si c'est "inbound",
    # le client attend une réponse → la conversation est "à traiter".
    last_direction: dict[UUID, str] = {}
    if conv_ids:
        msg_rows = (
            await db.execute(
                select(
                    Message.conversation_id,
                    Message.content_text,
                    Message.direction,
                    Message.created_at,
                )
                .where(Message.conversation_id.in_(conv_ids))
                .order_by(Message.conversation_id, Message.created_at.desc())
            )
        ).all()
        for cid, text, direction, _created in msg_rows:
            if cid not in last_direction:
                last_direction[cid] = direction  # première ligne = message le plus récent
                if text:
                    previews[cid] = text[:160]

    conversations = []
    for conv, customer_name in rows:
        awaiting = last_direction.get(conv.id) == "inbound"
        wmin = _waiting_minutes(conv.last_message_at, now) if awaiting else None
        # SLA effectif tenant compte de la priorité et du canal (#7).
        sla_minutes = resolve_sla_minutes(
            biz, priority=conv.priority_level, channel=conv.channel
        )
        conversations.append(
            ConversationSummary(
                id=str(conv.id),
                channel=conv.channel,
                status=conv.status,
                priority_level=conv.priority_level or "medium",
                current_intent=conv.current_intent,
                message_count=conv.message_count or 0,
                is_escalated=conv.is_escalated,
                last_message_at=conv.last_message_at,
                customer_id=str(conv.customer_id) if conv.customer_id else None,
                customer_name=customer_name,
                last_message_preview=previews.get(conv.id),
                awaiting_reply=awaiting,
                overdue=awaiting and wmin is not None and wmin >= sla_minutes,
                waiting_minutes=wmin,
                sentiment=conv.sentiment,
                tags=list(conv.tags or []),
                created_at=conv.created_at,
            )
        )

    return ConversationListResponse(
        conversations=conversations, total=total, limit=limit, offset=offset
    )


class ConversationStats(BaseModel):
    awaiting: int


@router.get("/stats", response_model=ConversationStats)
async def conversation_stats(
    db: DbSession,
    principal: CurrentUser,
) -> ConversationStats:
    """Compteur léger : conversations « à traiter » (dernier message entrant)."""
    bid = principal.business_id
    if bid is None:
        return ConversationStats(awaiting=0)
    now = datetime.now(UTC)
    last_direction = (
        select(Message.direction)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    awaiting = (
        await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.business_id == bid,
                Conversation.status != "archived",
                or_(
                    Conversation.snoozed_until.is_(None),
                    Conversation.snoozed_until <= now,
                ),
                last_direction == "inbound",
            )
        )
    ).scalar_one()
    return ConversationStats(awaiting=int(awaiting or 0))


@router.get("/export.csv")
async def export_conversations_csv(
    db: DbSession,
    principal: CurrentUser,
) -> StreamingResponse:
    """Exporte les conversations du business au format CSV (toutes, hors limite raisonnable)."""
    bid = principal.business_id
    rows = []
    if bid is not None:
        rows = (
            await db.execute(
                select(Conversation, Customer.full_name)
                .outerjoin(Customer, Conversation.customer_id == Customer.id)
                .where(Conversation.business_id == bid)
                .order_by(
                    func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
                )
                .limit(5000)
            )
        ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "client",
            "canal",
            "statut",
            "messages",
            "attribuée_à",
            "étiquettes",
            "dernier_message",
            "créée_le",
        ]
    )
    for conv, customer_name in rows:
        writer.writerow(
            [
                str(conv.id),
                customer_name or "",
                conv.channel,
                conv.status,
                conv.message_count or 0,
                conv.assigned_to or "",
                ", ".join(conv.tags or []),
                conv.last_message_at.isoformat() if conv.last_message_at else "",
                conv.created_at.isoformat() if conv.created_at else "",
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=conversations.csv"},
    )


# ── Recherche plein-texte des messages (#8) ──────────────────────────────────


class MessageSearchHit(BaseModel):
    conversation_id: str
    message_id: str
    direction: str
    channel: str
    snippet: str
    customer_name: str | None = None
    created_at: datetime


class MessageSearchResponse(BaseModel):
    query: str
    hits: list[MessageSearchHit]
    total: int


def _snippet(content: str | None, query: str, width: int = 160) -> str:
    """Extrait un fragment centré sur la 1re occurrence du terme recherché."""
    text_val = (content or "").replace("\n", " ").strip()
    if not text_val:
        return ""
    low = text_val.lower()
    pos = low.find((query or "").lower().strip()[:40])
    if pos < 0 or len(text_val) <= width:
        return text_val[:width]
    start = max(0, pos - width // 3)
    end = min(len(text_val), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text_val) else ""
    return f"{prefix}{text_val[start:end]}{suffix}"


@router.get("/search/messages", response_model=MessageSearchResponse)
async def search_messages(
    db: DbSession,
    principal: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessageSearchResponse:
    """Recherche plein-texte dans le contenu des messages du business (#8).

    Sur Postgres : index GIN ``to_tsvector('french', …)`` + ``plainto_tsquery``
    (rapide, tolérant aux accents/stop-words). Ailleurs (SQLite de test) : repli
    sur ``ILIKE``. Renvoie les messages correspondants avec leur contexte.
    """
    bid = principal.business_id
    if bid is None:
        return MessageSearchResponse(query=q, hits=[], total=0)

    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"

    if dialect == "postgresql":
        sql = text(
            """
            SELECT m.id, m.conversation_id, m.direction, m.channel,
                   m.content_text, m.created_at, c.full_name
            FROM messages m
            JOIN conversations cv ON cv.id = m.conversation_id
            LEFT JOIN customers c ON c.id = cv.customer_id
            WHERE m.business_id = :bid
              AND to_tsvector('french', coalesce(m.content_text, ''))
                  @@ plainto_tsquery('french', :q)
            ORDER BY m.created_at DESC
            LIMIT :lim
            """
        )
        result = await db.execute(sql, {"bid": str(bid), "q": q, "lim": limit})
        records = result.all()
        count_sql = text(
            """
            SELECT count(*) FROM messages m
            WHERE m.business_id = :bid
              AND to_tsvector('french', coalesce(m.content_text, ''))
                  @@ plainto_tsquery('french', :q)
            """
        )
        total = (await db.execute(count_sql, {"bid": str(bid), "q": q})).scalar_one()
    else:
        pattern = f"%{q.strip()}%"
        base = (
            select(
                Message.id,
                Message.conversation_id,
                Message.direction,
                Message.channel,
                Message.content_text,
                Message.created_at,
                Customer.full_name,
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .outerjoin(Customer, Customer.id == Conversation.customer_id)
            .where(Message.business_id == bid, Message.content_text.ilike(pattern))
        )
        records = (
            await db.execute(base.order_by(Message.created_at.desc()).limit(limit))
        ).all()
        total = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.business_id == bid, Message.content_text.ilike(pattern)
                )
            )
        ).scalar_one()

    hits = [
        MessageSearchHit(
            conversation_id=str(r[1]),
            message_id=str(r[0]),
            direction=r[2],
            channel=r[3],
            snippet=_snippet(r[4], q),
            customer_name=r[6],
            created_at=r[5],
        )
        for r in records
    ]
    return MessageSearchResponse(query=q, hits=hits, total=int(total or 0))


# ── Actions groupées (#1) ────────────────────────────────────────────────────


class BulkActionRequest(BaseModel):
    ids: list[UUID] = Field(..., min_length=1, max_length=200)
    action: Literal["status", "assign", "priority", "tag_add", "tag_remove"]
    value: str | None = Field(default=None, max_length=255)


class BulkActionResult(BaseModel):
    updated: int


@router.post("/bulk", response_model=BulkActionResult)
async def bulk_action(
    body: BulkActionRequest,
    db: DbSession,
    principal: CurrentUser,
) -> BulkActionResult:
    """Applique une action à plusieurs conversations d'un coup (#1).

    Actions : changer le statut, attribuer/libérer, changer la priorité, ajouter
    ou retirer une étiquette. Tout est scopé au business ; chaque modification
    est tracée dans le journal d'audit.
    """
    bid = principal.business_id
    if bid is None:
        return BulkActionResult(updated=0)
    actor = principal.email or "Agent"

    convs = (
        await db.execute(
            select(Conversation).where(
                Conversation.id.in_(body.ids), Conversation.business_id == bid
            )
        )
    ).scalars().all()
    if not convs:
        return BulkActionResult(updated=0)

    val = (body.value or "").strip()
    if body.action == "status" and val not in {"open", "closed", "archived"}:
        raise HTTPException(400, "Statut invalide")
    if body.action == "priority" and val not in PRIORITY_RANK:
        raise HTTPException(400, "Priorité invalide")

    updated = 0
    for conv in convs:
        if body.action == "status":
            conv.status = val
            summary = f"Statut → {val} (groupé)"
        elif body.action == "assign":
            conv.assigned_to = val or None
            summary = f"Attribuée à {val or 'personne'} (groupé)"
        elif body.action == "priority":
            conv.priority_level = val
            summary = f"Priorité → {val} (groupé)"
        elif body.action == "tag_add":
            if not val:
                continue
            current = list(conv.tags or [])
            if val.lower() not in {t.lower() for t in current}:
                current.append(val)
            conv.tags = current
            summary = f"Étiquette « {val} » ajoutée (groupé)"
        else:  # tag_remove
            if not val:
                continue
            conv.tags = [t for t in (conv.tags or []) if t.lower() != val.lower()]
            summary = f"Étiquette « {val} » retirée (groupé)"
        record_audit(
            db,
            business_id=bid,
            actor=actor,
            action=f"conversation.bulk_{body.action}",
            entity_type="conversation",
            entity_id=conv.id,
            summary=summary,
        )
        updated += 1

    await db.commit()
    for conv in convs:
        publish_conversation_event(
            bid, conversation_id=conv.id, kind="status", channel=conv.channel
        )
    logger.info("conversation.bulk", action=body.action, count=updated)
    return BulkActionResult(updated=updated)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> ConversationDetail:
    """Détail d'une conversation avec tous ses messages (scopé au business)."""
    bid = principal.business_id
    row = (
        await db.execute(
            select(Conversation, Customer.full_name)
            .outerjoin(Customer, Conversation.customer_id == Customer.id)
            .where(Conversation.id == conversation_id, Conversation.business_id == bid)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Conversation introuvable")
    conv, customer_name = row

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()

    return ConversationDetail(
        id=str(conv.id),
        channel=conv.channel,
        status=conv.status,
        priority_level=conv.priority_level or "medium",
        current_intent=conv.current_intent,
        message_count=conv.message_count or 0,
        is_escalated=conv.is_escalated,
        last_message_at=conv.last_message_at,
        summary=conv.summary,
        customer_id=str(conv.customer_id) if conv.customer_id else None,
        customer_name=customer_name,
        assigned_to=conv.assigned_to,
        sentiment=conv.sentiment,
        snoozed_until=conv.snoozed_until,
        tags=list(conv.tags or []),
        created_at=conv.created_at,
        messages=[
            ConversationMessage(
                id=str(m.id),
                direction=m.direction,
                sender_name=m.sender_name,
                content=m.content_text,
                channel=m.channel,
                status=m.status,
                attachment_count=m.attachment_count or 0,
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


class ReplyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class ReplyResult(BaseModel):
    message: ConversationMessage
    delivered: bool
    assigned_to: str | None = None


@router.post("/{conversation_id}/reply", response_model=ReplyResult)
async def reply_to_conversation(
    conversation_id: UUID,
    body: ReplyRequest,
    db: DbSession,
    principal: CurrentUser,
) -> ReplyResult:
    """Réponse humaine à un client depuis le dashboard (reprise en main).

    Envoie le message sur le canal d'origine (best-effort, selon le connecteur)
    et le persiste. La conversation est marquée ``assigned_to`` : Jenny cesse de
    répondre automatiquement sur ce fil (l'humain a pris la main).
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")

    delivered = await send_channel_reply(conv.channel, conv.external_conversation_id, body.text)

    now = datetime.now(UTC)
    agent = principal.email or "Agent"
    msg = Message(
        conversation_id=conv.id,
        business_id=conv.business_id,
        external_message_id=str(uuid4()),
        channel=conv.channel,
        direction="outbound",
        sender_name=agent,
        content_text=body.text,
        status="responded" if delivered else "failed",
        received_at=now,
        source_created_at=now,
    )
    db.add(msg)
    conv.assigned_to = agent  # reprise humaine → Jenny se met en pause sur ce fil
    conv.message_count = (conv.message_count or 0) + 1
    conv.last_message_at = now
    conv.last_message_preview = body.text[:200]
    record_audit(
        db,
        business_id=conv.business_id,
        actor=agent,
        action="conversation.replied",
        entity_type="conversation",
        entity_id=conv.id,
        summary=f"Réponse envoyée ({conv.channel})",
        meta={"delivered": delivered},
    )
    await db.commit()
    await db.refresh(msg)

    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="outbound", channel=conv.channel
    )
    logger.info(
        "conversation.human_reply",
        conversation_id=str(conv.id),
        channel=conv.channel,
        delivered=delivered,
    )
    return ReplyResult(
        message=ConversationMessage(
            id=str(msg.id),
            direction=msg.direction,
            sender_name=msg.sender_name,
            content=msg.content_text,
            channel=msg.channel,
            status=msg.status,
            created_at=msg.created_at,
        ),
        delivered=delivered,
        assigned_to=conv.assigned_to,
    )


class SuggestResult(BaseModel):
    suggestion: str
    variants: list[str] = Field(default_factory=list)


@router.post("/{conversation_id}/suggest", response_model=SuggestResult)
async def suggest_reply(
    conversation_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> SuggestResult:
    """Propose un brouillon de réponse (généré par le moteur) au dernier message client.

    Sert à l'agent qui a repris la main : il obtient une suggestion rédigée,
    qu'il peut éditer avant de l'envoyer. Rien n'est persisté ni envoyé ici.
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")

    last_inbound = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.direction == "inbound")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if last_inbound is None or not last_inbound.content_text:
        raise HTTPException(400, "Aucun message client à traiter")

    persona, business_name = await load_business_persona(db, conv.business_id)
    out = await get_engine().process(
        EngineRequest(
            conversation_id=conv.id,
            business_id=conv.business_id,
            message_text=last_inbound.content_text,
            channel=conv.channel,
            persona=persona,
            business_name=business_name,
        )
    )
    base = out.response_text
    variants = [base]
    # 2 reformulations alternatives (ton légèrement différent) via le LLM.
    rg = getattr(get_engine(), "response_generator", None)
    provider = getattr(rg, "llm", None)
    if provider is not None:
        try:
            alt = await provider.generate(
                prompt=(
                    "Reformule ce message client de 2 façons différentes (ton "
                    "légèrement différent), une par ligne, sans numérotation ni "
                    f"puce, dans la même langue :\n\n{base}"
                ),
                system_prompt="Tu reformules des réponses de support, en gardant le sens.",
                max_tokens=220,
            )
            for line in (alt.content or "").splitlines():
                t = line.strip().lstrip("-•*0123456789. ").strip()
                if t and t not in variants:
                    variants.append(t)
        except Exception as exc:
            logger.warning("conversation.suggest_variants_failed", error=str(exc))
    logger.info("conversation.suggested", conversation_id=str(conv.id))
    return SuggestResult(suggestion=base, variants=variants[:3])


class AssignmentResult(BaseModel):
    assigned_to: str | None = None


@router.post("/{conversation_id}/resume", response_model=AssignmentResult)
async def resume_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> AssignmentResult:
    """Rend la main à Jenny : libère la conversation (``assigned_to = None``).

    Jenny recommence alors à répondre automatiquement aux prochains messages
    du client sur ce fil. Idempotent.
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    conv.assigned_to = None
    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    logger.info("conversation.resumed_by_jenny", conversation_id=str(conv.id))
    return AssignmentResult(assigned_to=None)


class AssignRequest(BaseModel):
    assignee: str | None = Field(default=None, max_length=255)


@router.post("/{conversation_id}/assign", response_model=AssignmentResult)
async def assign_conversation(
    conversation_id: UUID,
    body: AssignRequest,
    db: DbSession,
    principal: CurrentUser,
) -> AssignmentResult:
    """Attribue la conversation à un membre (``assignee`` = email) ou la libère.

    Tant qu'une conversation est attribuée, Jenny ne répond plus
    automatiquement (un humain en a la charge). ``assignee = null`` la libère
    (équivalent à « rendre la main à Jenny »).
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    actor = principal.email or "Agent"
    new_assignee = body.assignee or None
    conv.assigned_to = new_assignee

    record_audit(
        db,
        business_id=conv.business_id,
        actor=actor,
        action="conversation.assigned",
        entity_type="conversation",
        entity_id=conv.id,
        summary=f"Conversation attribuée à {new_assignee or 'personne'}",
    )
    # Notifie l'agent ciblé, sauf s'il s'attribue lui-même la conversation (#15).
    notif = None
    if new_assignee and new_assignee != actor:
        cust = await db.scalar(
            select(Customer.full_name).where(Customer.id == conv.customer_id)
        )
        notif = build_notification(
            db,
            business_id=conv.business_id,
            recipient=new_assignee,
            kind="assigned",
            title="Une conversation vous a été attribuée",
            body=f"{cust or 'Client'} · {conv.channel}",
            conversation_id=conv.id,
            meta={"by": actor},
        )

    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    if notif is not None:
        await db.refresh(notif)
        publish_notification_event(
            conv.business_id,
            recipient=new_assignee,
            kind="assigned",
            title="Une conversation vous a été attribuée",
            conversation_id=conv.id,
            notification_id=notif.id,
        )
    logger.info(
        "conversation.assigned", conversation_id=str(conv.id), assignee=conv.assigned_to
    )
    return AssignmentResult(assigned_to=conv.assigned_to)


class StatusUpdate(BaseModel):
    status: Literal["open", "closed", "archived"]


class StatusResult(BaseModel):
    status: str


@router.patch("/{conversation_id}/status", response_model=StatusResult)
async def update_conversation_status(
    conversation_id: UUID,
    body: StatusUpdate,
    db: DbSession,
    principal: CurrentUser,
) -> StatusResult:
    """Change le statut d'une conversation : ouverte, résolue (closed) ou archivée."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    previous = conv.status
    conv.status = body.status
    record_audit(
        db,
        business_id=conv.business_id,
        actor=principal.email or "Agent",
        action="conversation.status_changed",
        entity_type="conversation",
        entity_id=conv.id,
        summary=f"Statut : {previous} → {body.status}",
        meta={"from": previous, "to": body.status},
    )
    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    logger.info(
        "conversation.status_changed", conversation_id=str(conv.id), status=body.status
    )
    return StatusResult(status=conv.status)


class PriorityUpdate(BaseModel):
    priority_level: Literal["low", "medium", "high", "critical"]


class PriorityResult(BaseModel):
    priority_level: str


@router.patch("/{conversation_id}/priority", response_model=PriorityResult)
async def update_conversation_priority(
    conversation_id: UUID,
    body: PriorityUpdate,
    db: DbSession,
    principal: CurrentUser,
) -> PriorityResult:
    """Change la priorité d'une conversation (low/medium/high/critical) (#4)."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    previous = conv.priority_level
    conv.priority_level = body.priority_level
    record_audit(
        db,
        business_id=conv.business_id,
        actor=principal.email or "Agent",
        action="conversation.priority_changed",
        entity_type="conversation",
        entity_id=conv.id,
        summary=f"Priorité : {previous} → {body.priority_level}",
        meta={"from": previous, "to": body.priority_level},
    )
    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    logger.info(
        "conversation.priority_changed",
        conversation_id=str(conv.id),
        priority=body.priority_level,
    )
    return PriorityResult(priority_level=conv.priority_level)


class TagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)


class TagsResult(BaseModel):
    tags: list[str]


@router.patch("/{conversation_id}/tags", response_model=TagsResult)
async def update_conversation_tags(
    conversation_id: UUID,
    body: TagsUpdate,
    db: DbSession,
    principal: CurrentUser,
) -> TagsResult:
    """Remplace les étiquettes d'une conversation (liste de chaînes)."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    # Normalise : trim, dédoublonne en gardant l'ordre, ignore les vides.
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in body.tags:
        t = raw.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            cleaned.append(t)
    conv.tags = cleaned
    record_audit(
        db,
        business_id=conv.business_id,
        actor=principal.email or "Agent",
        action="conversation.tags_updated",
        entity_type="conversation",
        entity_id=conv.id,
        summary=f"Étiquettes : {', '.join(cleaned) or '(aucune)'}",
        meta={"tags": cleaned},
    )
    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    logger.info("conversation.tags_updated", conversation_id=str(conv.id), count=len(cleaned))
    return TagsResult(tags=cleaned)


class SnoozeRequest(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)


class SnoozeResult(BaseModel):
    snoozed_until: datetime | None = None


@router.post("/{conversation_id}/snooze", response_model=SnoozeResult)
async def snooze_conversation(
    conversation_id: UUID,
    body: SnoozeRequest,
    db: DbSession,
    principal: CurrentUser,
) -> SnoozeResult:
    """Reporte (snooze) une conversation : masquée de la vue active jusqu'à
    ``now + minutes``. ``minutes = null`` annule le report."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")
    if body.minutes is None:
        conv.snoozed_until = None
    else:
        conv.snoozed_until = datetime.now(UTC) + timedelta(minutes=body.minutes)
    await db.commit()
    publish_conversation_event(
        conv.business_id, conversation_id=conv.id, kind="status", channel=conv.channel
    )
    logger.info("conversation.snoozed", conversation_id=str(conv.id), until=str(conv.snoozed_until))
    return SnoozeResult(snoozed_until=conv.snoozed_until)


class SummaryResult(BaseModel):
    summary: str


@router.post("/{conversation_id}/summarize", response_model=SummaryResult)
async def summarize_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> SummaryResult:
    """Génère (via LLM) un résumé concis de la conversation et le persiste."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.business_id != principal.business_id:
        raise HTTPException(404, "Conversation introuvable")

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
            .limit(50)
        )
    ).scalars().all()
    if not msgs:
        raise HTTPException(400, "Conversation vide")

    transcript = "\n".join(
        f"{'Client' if m.direction == 'inbound' else 'Vous'}: {m.content_text}"
        for m in msgs
        if m.content_text
    )
    rg = getattr(get_engine(), "response_generator", None)
    provider = getattr(rg, "llm", None)  # réutilise le provider LLM configuré
    summary = ""
    if provider is not None:
        out = await provider.generate(
            prompt=f"Résume cette conversation client en 1 à 2 phrases, en français:\n\n{transcript}",
            system_prompt="Tu résumes des conversations de support de façon factuelle et concise.",
            max_tokens=120,
        )
        summary = (out.content or "").strip()
    if not summary:
        # Repli sans LLM : aperçu du premier message client.
        first_in = next((m.content_text for m in msgs if m.direction == "inbound"), "")
        summary = (first_in or "Conversation")[:200]

    conv.summary = summary
    await db.commit()
    logger.info("conversation.summarized", conversation_id=str(conv.id))
    return SummaryResult(summary=summary)


class MergeRequest(BaseModel):
    source_id: UUID


class MergeResult(BaseModel):
    target_id: str
    merged_messages: int
    message_count: int


@router.post("/{conversation_id}/merge", response_model=MergeResult)
async def merge_conversations(
    conversation_id: UUID,
    body: MergeRequest,
    db: DbSession,
    principal: CurrentUser,
) -> MergeResult:
    """Fusionne la conversation ``source_id`` dans ``conversation_id`` (cible) (#10).

    Tous les messages de la source sont rattachés à la cible (ordre chronologique
    préservé), les étiquettes fusionnées, les compteurs recalculés ; la source est
    archivée. Utile quand un même client a écrit via deux fils distincts.
    """
    bid = principal.business_id
    target = await db.get(Conversation, conversation_id)
    if target is None or target.business_id != bid:
        raise HTTPException(404, "Conversation cible introuvable")
    if body.source_id == conversation_id:
        raise HTTPException(400, "Impossible de fusionner une conversation avec elle-même")
    source = await db.get(Conversation, body.source_id)
    if source is None or source.business_id != bid:
        raise HTTPException(404, "Conversation source introuvable")

    res = await db.execute(
        update(Message)
        .where(Message.conversation_id == source.id)
        .values(conversation_id=target.id)
    )
    moved = res.rowcount or 0

    # Recalcule les compteurs et le dernier message de la cible.
    target.message_count = (
        await db.scalar(
            select(func.count(Message.id)).where(Message.conversation_id == target.id)
        )
    ) or 0
    last = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == target.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if last is not None:
        target.last_message_at = last.created_at
        target.last_message_preview = (last.content_text or "")[:200]

    # Fusionne les étiquettes (union, sans doublon, ordre stable).
    merged_tags = list(target.tags or [])
    seen = {t.lower() for t in merged_tags}
    for t in source.tags or []:
        if t.lower() not in seen:
            seen.add(t.lower())
            merged_tags.append(t)
    target.tags = merged_tags

    source.status = "archived"
    source.message_count = 0
    source.last_message_preview = "Fusionnée dans une autre conversation"

    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "Agent",
        action="conversation.merged",
        entity_type="conversation",
        entity_id=target.id,
        summary=f"Fusion de {moved} message(s) depuis une autre conversation",
        meta={"source_id": str(source.id), "moved": moved},
    )
    await db.commit()

    publish_conversation_event(
        bid, conversation_id=target.id, kind="update", channel=target.channel
    )
    publish_conversation_event(
        bid, conversation_id=source.id, kind="status", channel=source.channel
    )
    logger.info(
        "conversation.merged",
        target=str(target.id),
        source=str(source.id),
        moved=moved,
    )
    return MergeResult(
        target_id=str(target.id), merged_messages=moved, message_count=target.message_count
    )
