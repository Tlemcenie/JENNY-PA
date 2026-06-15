"""Service RGPD — portabilité (export) et droit à l'effacement (anonymisation).

Deux opérations sur les données d'un client, toujours scopées au business :

- ``export_customer_data`` : rassemble TOUT ce que le salon détient sur le client
  (profil, RDV, conversations, messages, faits, transactions, commandes, tickets,
  liste d'attente) en un bundle JSON portable.
- ``anonymize_customer`` : efface les données personnelles (droit à l'oubli) en
  conservant les écritures utiles à la comptabilité (RDV, transactions) mais en
  les détachant de toute information identifiante. Idempotent.

Aucune suppression « dure » de lignes comptables : on anonymise sur place, ce qui
est la voie RGPD recommandée (effacement des données personnelles, conservation
des obligations légales).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from jenny.core.logging import get_logger
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.customer_address import CustomerAddress
from jenny.domain.models.customer_document import CustomerDocument
from jenny.domain.models.customer_fact import CustomerFact
from jenny.domain.models.customer_transaction import CustomerTransaction
from jenny.domain.models.message import Message
from jenny.domain.models.order import Order
from jenny.domain.models.pending_question import PendingQuestion
from jenny.domain.models.support_ticket import SupportTicket
from jenny.domain.models.waitlist_entry import WaitlistEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

_ANON_NAME = "Client anonymisé"
_SCRUBBED = "[supprimé — RGPD]"


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _row(obj: object, fields: tuple[str, ...]) -> dict:
    """Sérialise des attributs d'un modèle en dict JSON-compatible."""
    out: dict[str, Any] = {}
    for f in fields:
        val = getattr(obj, f, None)
        out[f] = str(val) if isinstance(val, UUID) else _iso(val)
    return out


async def _fetch(db: AsyncSession, model, business_id: UUID, customer_id: UUID) -> list:
    return list(
        (
            await db.execute(
                select(model).where(
                    model.business_id == business_id, model.customer_id == customer_id
                )
            )
        ).scalars().all()
    )


async def export_customer_data(
    db: AsyncSession, *, business_id: UUID, customer_id: UUID
) -> dict | None:
    """Bundle JSON portable de toutes les données d'un client. None si introuvable."""
    customer = await db.get(Customer, customer_id)
    if customer is None or customer.business_id != business_id:
        return None

    conversations = await _fetch(db, Conversation, business_id, customer_id)
    messages = await _fetch(db, Message, business_id, customer_id)
    appointments = await _fetch(db, Appointment, business_id, customer_id)
    addresses = await _fetch(db, CustomerAddress, business_id, customer_id)
    documents = await _fetch(db, CustomerDocument, business_id, customer_id)
    facts = await _fetch(db, CustomerFact, business_id, customer_id)
    transactions = await _fetch(db, CustomerTransaction, business_id, customer_id)
    orders = await _fetch(db, Order, business_id, customer_id)
    tickets = await _fetch(db, SupportTicket, business_id, customer_id)
    waitlist = await _fetch(db, WaitlistEntry, business_id, customer_id)

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "profile": _row(
            customer,
            (
                "id", "full_name", "email", "phone", "instagram_handle", "messenger_id",
                "tags", "notes", "first_seen_at", "last_seen_at", "anonymized_at",
                "created_at",
            ),
        ),
        "appointments": [
            _row(a, ("id", "title", "status", "start_at", "end_at", "channel",
                     "deposit_cents", "deposit_status"))
            for a in appointments
        ],
        "conversations": [
            _row(c, ("id", "channel", "status", "message_count", "created_at",
                     "last_message_at"))
            for c in conversations
        ],
        "messages": [
            _row(m, ("id", "direction", "channel", "content_text", "language",
                     "received_at"))
            for m in messages
        ],
        "facts": [
            _row(f, ("id", "fact", "fact_key", "kind", "source", "last_seen_at")) for f in facts
        ],
        "transactions": [
            _row(t, ("id", "amount_minor", "currency", "status", "occurred_at"))
            for t in transactions
        ],
        "orders": [
            _row(o, ("id", "reference", "status", "currency", "total_amount_minor"))
            for o in orders
        ],
        "support_tickets": [
            _row(t, ("id", "reference", "subject", "status", "priority")) for t in tickets
        ],
        "addresses": [
            _row(a, ("id", "label", "line1", "line2", "city", "region", "postal_code", "country"))
            for a in addresses
        ],
        "documents": [
            _row(d, ("id", "title", "file_name", "mime_type", "size_bytes", "created_at"))
            for d in documents
        ],
        "waitlist": [
            _row(w, ("id", "service", "desired_window", "status", "created_at")) for w in waitlist
        ],
        "counts": {
            "appointments": len(appointments),
            "conversations": len(conversations),
            "messages": len(messages),
            "facts": len(facts),
            "transactions": len(transactions),
            "orders": len(orders),
            "support_tickets": len(tickets),
            "addresses": len(addresses),
            "documents": len(documents),
            "waitlist": len(waitlist),
        },
    }


async def anonymize_customer(
    db: AsyncSession, *, business_id: UUID, customer_id: UUID
) -> dict | None:
    """Efface les données personnelles d'un client (droit à l'oubli). Idempotent.

    Détache le profil de toute PII, supprime les sous-données personnelles
    (adresses, documents, faits), neutralise le contenu des messages et de la liste
    d'attente. Conserve les écritures comptables (RDV, transactions, commandes) mais
    sans lien identifiant. Renvoie un récapitulatif, ou None si client introuvable.
    """
    customer = await db.get(Customer, customer_id)
    if customer is None or customer.business_id != business_id:
        return None
    if customer.anonymized_at is not None:
        return {"already_anonymized": True, "customer_id": str(customer_id)}

    # 1) Profil : on retire toute information identifiante.
    customer.full_name = _ANON_NAME
    customer.email = None
    customer.phone = None
    customer.instagram_handle = None
    customer.messenger_id = None
    customer.notes = None
    customer.tags = None
    customer.anonymized_at = datetime.now(UTC)

    # 2) Sous-données strictement personnelles → suppression.
    deleted = {"addresses": 0, "documents": 0, "facts": 0}
    for model, key in ((CustomerAddress, "addresses"), (CustomerDocument, "documents"), (CustomerFact, "facts")):
        rows = await _fetch(db, model, business_id, customer_id)
        for r in rows:
            await db.delete(r)
        deleted[key] = len(rows)

    # 3) Messages : on neutralise le contenu ET l'expéditeur (PII), trace technique gardée.
    msgs = await _fetch(db, Message, business_id, customer_id)
    for m in msgs:
        m.content_text = _SCRUBBED
        m.content_html = None
        m.cleaned_text = None
        m.subject = None
        m.sender_email = None
        m.sender_phone = None
        m.sender_handle = None
        if getattr(m, "sender_name", None):
            m.sender_name = _ANON_NAME
    scrubbed_messages = len(msgs)

    # 4) Liste d'attente : on retire le contact et on clôt l'entrée.
    wl = await _fetch(db, WaitlistEntry, business_id, customer_id)
    for w in wl:
        w.customer_name = None
        w.customer_contact = None
        w.note = None
        if w.status in ("waiting", "notified"):
            w.status = "cancelled"

    # 5) Questions en attente : on neutralise le texte (mots du client).
    pq = await _fetch(db, PendingQuestion, business_id, customer_id)
    for q in pq:
        q.question = _SCRUBBED

    logger.info(
        "privacy.anonymized",
        business_id=str(business_id),
        customer_id=str(customer_id),
        messages=scrubbed_messages,
    )
    return {
        "anonymized": True,
        "customer_id": str(customer_id),
        "deleted": deleted,
        "scrubbed_messages": scrubbed_messages,
        "cancelled_waitlist": len(wl),
    }
