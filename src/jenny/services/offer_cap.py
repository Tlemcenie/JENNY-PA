"""Plafond anti-spam des messages commerciaux.

Par défaut : une offre (créneau libre, campagne) par client et par
semaine. Les rappels de RDV et les confirmations n'y passent pas.
Un client qui répond STOP ne reçoit plus rien de commercial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case, or_, update
from sqlalchemy.orm.attributes import set_committed_value

from jenny.core.logging import get_logger
from jenny.domain.models.customer import Customer

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

WINDOW = timedelta(days=7)
DEFAULT_MAX_PER_WEEK = 1


def _aware(dt: datetime | None) -> datetime | None:
    """Datetime naïve -> UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def can_offer(
    customer: Customer | None,
    now: datetime | None = None,
    max_per_week: int = DEFAULT_MAX_PER_WEEK,
) -> bool:
    """Vrai si on peut lui envoyer une offre."""
    if customer is None or max_per_week <= 0:
        return False
    if customer.anonymized_at is not None or customer.marketing_opt_out_at is not None:
        return False
    now = _aware(now) or datetime.now(UTC)
    start = _aware(customer.offer_window_start)
    if start is None or now - start >= WINDOW:
        return True
    return int(customer.offer_window_count or 0) < max_per_week


@dataclass(slots=True)
class OfferClaim:
    """Place prise dans le plafond."""

    customer_id: UUID
    prev_last: datetime | None
    prev_start: datetime | None
    prev_count: int


def _sync(customer: Customer, last, start, count) -> None:
    """Recale l'objet sans le salir."""
    set_committed_value(customer, "last_offer_at", last)
    set_committed_value(customer, "offer_window_start", start)
    set_committed_value(customer, "offer_window_count", count)


async def claim_offer(
    db: AsyncSession,
    customer: Customer,
    *,
    now: datetime | None = None,
    max_per_week: int = DEFAULT_MAX_PER_WEEK,
) -> OfferClaim | None:
    """Prend une place, en une requête atomique."""
    now = _aware(now) or datetime.now(UTC)
    if not can_offer(customer, now, max_per_week):
        return None
    expired = or_(
        Customer.offer_window_start.is_(None),
        Customer.offer_window_start <= now - WINDOW,
    )
    stmt = (
        update(Customer)
        .where(
            Customer.id == customer.id,
            Customer.anonymized_at.is_(None),
            Customer.marketing_opt_out_at.is_(None),
            or_(expired, Customer.offer_window_count < max_per_week),
        )
        .values(
            last_offer_at=now,
            offer_window_start=case((expired, now), else_=Customer.offer_window_start),
            offer_window_count=case((expired, 1), else_=Customer.offer_window_count + 1),
        )
        .execution_options(synchronize_session=False)
    )
    res = await db.execute(stmt)
    if res.rowcount != 1:
        # un autre envoi est passé avant
        return None
    claim = OfferClaim(
        customer_id=customer.id,
        prev_last=customer.last_offer_at,
        prev_start=customer.offer_window_start,
        prev_count=int(customer.offer_window_count or 0),
    )
    start = _aware(customer.offer_window_start)
    if start is None or now - start >= WINDOW:
        _sync(customer, now, now, 1)
    else:
        _sync(customer, now, customer.offer_window_start, claim.prev_count + 1)
    return claim


async def release_offer(
    db: AsyncSession, claim: OfferClaim, customer: Customer | None = None
) -> None:
    """Rend la place si l'envoi a raté."""
    await db.execute(
        update(Customer)
        .where(Customer.id == claim.customer_id)
        .values(
            last_offer_at=claim.prev_last,
            offer_window_start=claim.prev_start,
            offer_window_count=claim.prev_count,
        )
        .execution_options(synchronize_session=False)
    )
    if customer is not None:
        _sync(customer, claim.prev_last, claim.prev_start, claim.prev_count)


# ── désinscription ──

_STOP_RE = re.compile(
    r"^\s*(stop|arr[eê]t|arr[eê]te[rz]?|d[ée]sinscri\w*|unsubscribe|stop\s+pub)\s*[.!]*\s*$",
    re.I,
)


def is_stop_reply(text: str | None) -> bool:
    """Le client a répondu STOP ?"""
    return bool(text) and bool(_STOP_RE.match(text))


def set_opt_out(customer: Customer, opt_out: bool, now: datetime | None = None) -> None:
    """Coche ou décoche la désinscription."""
    customer.marketing_opt_out_at = (_aware(now) or datetime.now(UTC)) if opt_out else None


async def apply_stop_reply(
    db: AsyncSession, *, business_id: UUID, customer_id: UUID | None, text: str | None
) -> bool:
    """Désinscrit si le message est un STOP."""
    if customer_id is None or not is_stop_reply(text):
        return False
    cust = await db.get(Customer, customer_id)
    if cust is None or cust.business_id != business_id:
        return False
    if cust.marketing_opt_out_at is None:
        set_opt_out(cust, True)
        logger.info("offer_cap.opt_out", customer_id=str(customer_id))
    return True
