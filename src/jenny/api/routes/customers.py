"""Fiche client 360° : tout ce qu'on sait d'un client, au même endroit.

Agrège, pour un client scopé au business du JWT :
- son identité et ses coordonnées (tous canaux confondus) ;
- ses conversations, commandes, transactions et tickets ;
- des statistiques de synthèse (dépensé, nb de commandes, etc.).

Le ``PATCH`` permet à l'agent d'annoter le client (notes internes, tags).
"""

import csv
import io
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.customer_transaction import CustomerTransaction
from jenny.domain.models.order import Order
from jenny.domain.models.support_ticket import SupportTicket
from jenny.domain.models.transaction_type import TransactionType

logger = get_logger(__name__)

router = APIRouter(prefix="/customers", tags=["Customers"])

# Statuts considérés comme « encaissés » pour le total dépensé.
_PAID_STATES = frozenset({"succeeded", "completed", "paid", "captured", "success"})
# Statuts de commande à exclure du chiffre d'affaires.
_DEAD_ORDER_STATES = frozenset({"cancelled", "canceled", "refunded", "draft"})


class CustomerConversationItem(BaseModel):
    id: str
    channel: str
    status: str
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime


class CustomerOrderItem(BaseModel):
    id: str
    reference: str | None = None
    status: str
    currency: str
    total_amount_minor: int | None = None
    created_at: datetime


class CustomerTransactionItem(BaseModel):
    id: str
    label: str
    amount_minor: int
    currency: str
    status: str
    occurred_at: datetime


class CustomerTicketItem(BaseModel):
    id: str
    reference: str | None = None
    subject: str | None = None
    status: str
    priority: str
    created_at: datetime


class CustomerStats(BaseModel):
    conversations: int
    messages: int
    orders: int
    open_tickets: int
    total_spent_minor: int
    currency: str


class Customer360(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    instagram_handle: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    created_at: datetime
    stats: CustomerStats
    conversations: list[CustomerConversationItem]
    orders: list[CustomerOrderItem]
    transactions: list[CustomerTransactionItem]
    tickets: list[CustomerTicketItem]


async def _load_customer(db: DbSession, customer_id: UUID, business_id: UUID | None) -> Customer:
    cust = await db.get(Customer, customer_id)
    if cust is None or cust.business_id != business_id:
        raise HTTPException(404, "Client introuvable")
    return cust


class CustomerListItem(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    instagram_handle: str | None = None
    tags: list[str] = Field(default_factory=list)
    conversation_count: int = 0
    last_seen_at: datetime | None = None
    created_at: datetime


class CustomerListResponse(BaseModel):
    customers: list[CustomerListItem]
    total: int
    limit: int
    offset: int


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    db: DbSession,
    principal: CurrentUser,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerListResponse:
    """Liste les clients du business (les plus récemment actifs d'abord).

    ``search`` filtre sur le nom, l'email ou le téléphone.
    """
    bid = principal.business_id
    if bid is None:
        return CustomerListResponse(customers=[], total=0, limit=limit, offset=offset)

    filters = [Customer.business_id == bid]
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                Customer.full_name.ilike(pattern),
                Customer.email.ilike(pattern),
                Customer.phone.ilike(pattern),
            )
        )

    total = (await db.execute(select(func.count(Customer.id)).where(*filters))).scalar_one()

    # Nombre de conversations par client (sous-requête agrégée).
    conv_counts = (
        select(
            Conversation.customer_id.label("cid"),
            func.count(Conversation.id).label("cnt"),
        )
        .where(Conversation.business_id == bid)
        .group_by(Conversation.customer_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(Customer, func.coalesce(conv_counts.c.cnt, 0))
            .outerjoin(conv_counts, Customer.id == conv_counts.c.cid)
            .where(*filters)
            .order_by(func.coalesce(Customer.last_seen_at, Customer.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    customers = [
        CustomerListItem(
            id=str(cust.id),
            full_name=cust.full_name,
            email=cust.email,
            phone=cust.phone,
            instagram_handle=cust.instagram_handle,
            tags=list(cust.tags or []),
            conversation_count=int(count or 0),
            last_seen_at=cust.last_seen_at,
            created_at=cust.created_at,
        )
        for cust, count in rows
    ]

    return CustomerListResponse(customers=customers, total=total, limit=limit, offset=offset)


class ImportResult(BaseModel):
    created: int
    skipped: int


@router.post("/import", response_model=ImportResult)
async def import_customers_csv(
    db: DbSession,
    principal: CurrentUser,
    file: Annotated[UploadFile, File(...)],
) -> ImportResult:
    """Importe des clients depuis un CSV (colonnes nom/email/téléphone, tolérant).

    Les doublons (même email) sont ignorés.
    """
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")

    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    now = datetime.now(UTC)
    created = 0
    skipped = 0
    for row in reader:
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = low.get("nom") or low.get("name") or low.get("full_name") or None
        email = low.get("email") or None
        phone = low.get("téléphone") or low.get("telephone") or low.get("phone") or None
        if not (name or email or phone):
            continue
        if email:
            exists = (
                await db.execute(
                    select(Customer.id).where(
                        Customer.business_id == bid, Customer.email == email
                    )
                )
            ).scalar_one_or_none()
            if exists:
                skipped += 1
                continue
        db.add(
            Customer(
                business_id=bid,
                full_name=name,
                email=email,
                phone=phone,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        created += 1
    await db.commit()
    logger.info("customers.imported", business_id=str(bid), created=created, skipped=skipped)
    return ImportResult(created=created, skipped=skipped)


@router.get("/export.csv")
async def export_customers_csv(
    db: DbSession,
    principal: CurrentUser,
) -> StreamingResponse:
    """Exporte les clients du business au format CSV."""
    bid = principal.business_id
    rows = []
    if bid is not None:
        conv_counts = (
            select(
                Conversation.customer_id.label("cid"),
                func.count(Conversation.id).label("cnt"),
            )
            .where(Conversation.business_id == bid)
            .group_by(Conversation.customer_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(Customer, func.coalesce(conv_counts.c.cnt, 0))
                .outerjoin(conv_counts, Customer.id == conv_counts.c.cid)
                .where(Customer.business_id == bid)
                .order_by(func.coalesce(Customer.last_seen_at, Customer.created_at).desc())
                .limit(5000)
            )
        ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "nom", "email", "téléphone", "instagram", "étiquettes", "conversations", "vu_le"]
    )
    for cust, count in rows:
        writer.writerow(
            [
                str(cust.id),
                cust.full_name or "",
                cust.email or "",
                cust.phone or "",
                cust.instagram_handle or "",
                ", ".join(cust.tags or []),
                int(count or 0),
                cust.last_seen_at.isoformat() if cust.last_seen_at else "",
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clients.csv"},
    )


@router.get("/{customer_id}", response_model=Customer360)
async def get_customer_360(
    customer_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> Customer360:
    """Vue 360° d'un client : identité, historique et synthèse financière."""
    bid = principal.business_id
    cust = await _load_customer(db, customer_id, bid)

    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.customer_id == customer_id)
            .order_by(
                func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
            )
            .limit(50)
        )
    ).scalars().all()

    orders = (
        await db.execute(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    tx_rows = (
        await db.execute(
            select(CustomerTransaction, TransactionType.label)
            .outerjoin(
                TransactionType,
                CustomerTransaction.transaction_type_id == TransactionType.id,
            )
            .where(CustomerTransaction.customer_id == customer_id)
            .order_by(CustomerTransaction.occurred_at.desc())
            .limit(50)
        )
    ).all()

    tickets = (
        await db.execute(
            select(SupportTicket)
            .where(SupportTicket.customer_id == customer_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    # ── Statistiques de synthèse (calculées en base, pas en Python) ──
    messages_total = (
        await db.execute(
            select(func.coalesce(func.sum(Conversation.message_count), 0)).where(
                Conversation.customer_id == customer_id
            )
        )
    ).scalar_one()

    open_tickets = (
        await db.execute(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.customer_id == customer_id,
                SupportTicket.status.notin_(["closed", "resolved"]),
            )
        )
    ).scalar_one()

    total_spent = (
        await db.execute(
            select(func.coalesce(func.sum(CustomerTransaction.amount_minor), 0)).where(
                CustomerTransaction.customer_id == customer_id,
                CustomerTransaction.status.in_(_PAID_STATES),
            )
        )
    ).scalar_one()

    currency = next((o.currency for o in orders), None) or next(
        (tx.currency for tx, _ in tx_rows), "EUR"
    )

    return Customer360(
        id=str(cust.id),
        full_name=cust.full_name,
        email=cust.email,
        phone=cust.phone,
        instagram_handle=cust.instagram_handle,
        tags=list(cust.tags or []),
        notes=cust.notes,
        first_seen_at=cust.first_seen_at,
        last_seen_at=cust.last_seen_at,
        created_at=cust.created_at,
        stats=CustomerStats(
            conversations=len(convs),
            messages=int(messages_total or 0),
            orders=len(orders),
            open_tickets=int(open_tickets or 0),
            total_spent_minor=int(total_spent or 0),
            currency=currency,
        ),
        conversations=[
            CustomerConversationItem(
                id=str(c.id),
                channel=c.channel,
                status=c.status,
                message_count=c.message_count or 0,
                last_message_at=c.last_message_at,
                created_at=c.created_at,
            )
            for c in convs
        ],
        orders=[
            CustomerOrderItem(
                id=str(o.id),
                reference=o.reference,
                status=o.status,
                currency=o.currency,
                total_amount_minor=o.total_amount_minor,
                created_at=o.created_at,
            )
            for o in orders
        ],
        transactions=[
            CustomerTransactionItem(
                id=str(tx.id),
                label=label or "Mouvement",
                amount_minor=tx.amount_minor,
                currency=tx.currency,
                status=tx.status,
                occurred_at=tx.occurred_at,
            )
            for tx, label in tx_rows
        ],
        tickets=[
            CustomerTicketItem(
                id=str(t.id),
                reference=t.reference,
                subject=t.subject,
                status=t.status,
                priority=t.priority,
                created_at=t.created_at,
            )
            for t in tickets
        ],
    )


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None)


class CustomerUpdateResult(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


@router.patch("/{customer_id}", response_model=CustomerUpdateResult)
async def update_customer(
    customer_id: UUID,
    body: CustomerUpdate,
    db: DbSession,
    principal: CurrentUser,
) -> CustomerUpdateResult:
    """Met à jour la fiche client (coordonnées, notes internes, tags).

    Seuls les champs fournis sont modifiés (``PATCH`` partiel).
    """
    cust = await _load_customer(db, customer_id, principal.business_id)

    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(cust, key, value)
    await db.commit()
    await db.refresh(cust)

    logger.info(
        "customer.updated", customer_id=str(cust.id), fields=sorted(fields.keys())
    )
    return CustomerUpdateResult(
        id=str(cust.id),
        full_name=cust.full_name,
        email=cust.email,
        phone=cust.phone,
        notes=cust.notes,
        tags=list(cust.tags or []),
    )
