"""Service liste d'attente — anti-no-show.

Quand le salon est complet, Jenny inscrit le client en liste d'attente
(``add_to_waitlist``). Dès qu'une annulation ou un déplacement libère un créneau,
le premier inscrit compatible est signalé au salon (``notify_waitlist_for_freed_slot``)
pour être recontacté en priorité : les trous se remplissent au lieu de rester vides.

Volontairement sans I/O réseau : tout passe par la session DB fournie par l'appelant,
qui maîtrise la transaction (commit côté action / handler). Robuste : les fonctions
ne lèvent pas sur cas limite, elles renvoient None / une entrée.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from jenny.core.logging import get_logger
from jenny.domain.models.notification import Notification
from jenny.domain.models.waitlist_entry import WaitlistEntry

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def _norm(value: str | None) -> str:
    """Normalise un nom de prestation pour comparaison (minuscule, sans espaces bords)."""
    return (value or "").strip().lower()


def _services_match(wanted: str | None, freed: str | None) -> bool:
    """Une entrée attend-elle ce créneau ? Vrai si même prestation (insensible à la
    casse, par inclusion : « coupe » ⊂ « coupe femme ») ou si l'un n'est pas précisé
    — un client sans prestation fixée prend ce qui se libère."""
    w, f = _norm(wanted), _norm(freed)
    if not w or not f:
        return True
    return w in f or f in w


async def add_to_waitlist(
    db: AsyncSession,
    *,
    business_id: UUID,
    service: str | None = None,
    desired_window: str | None = None,
    customer_id: UUID | None = None,
    conversation_id: UUID | None = None,
    customer_name: str | None = None,
    customer_contact: str | None = None,
    note: str | None = None,
) -> WaitlistEntry:
    """Inscrit un client en liste d'attente (sans doublon).

    Idempotent tant qu'une inscription « waiting » existe pour le même client (ou la
    même conversation) et la même prestation : un client qui réinsiste n'est pas
    inscrit deux fois. La transaction est laissée à l'appelant (pas de commit ici).
    """
    if customer_id is not None or conversation_id is not None:
        query = select(WaitlistEntry).where(
            WaitlistEntry.business_id == business_id,
            WaitlistEntry.status == "waiting",
        )
        if customer_id is not None:
            query = query.where(WaitlistEntry.customer_id == customer_id)
        else:
            query = query.where(WaitlistEntry.conversation_id == conversation_id)
        for existing in (await db.execute(query)).scalars().all():
            if _norm(existing.service) == _norm(service):
                logger.info("waitlist.add.dedup", entry_id=str(existing.id))
                return existing

    entry = WaitlistEntry(
        business_id=business_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        service=service or None,
        desired_window=(desired_window or None),
        customer_name=customer_name or None,
        customer_contact=customer_contact or None,
        note=note or None,
        status="waiting",
    )
    db.add(entry)
    await db.flush()
    logger.info(
        "waitlist.added",
        business_id=str(business_id),
        entry_id=str(entry.id),
        service=service,
    )
    return entry


async def waitlist_position(db: AsyncSession, entry: WaitlistEntry) -> int:
    """Rang de l'entrée dans la file (1 = prochain prévenu).

    Compte les inscriptions « waiting » du salon créées avant (ou en même temps que)
    celle-ci. Approximation suffisante : la file est traitée par ancienneté.
    """
    count = (
        await db.execute(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.business_id == entry.business_id,
                WaitlistEntry.status == "waiting",
                WaitlistEntry.created_at <= entry.created_at,
            )
        )
    ).scalar_one()
    return max(1, int(count or 1))


async def notify_waitlist_for_freed_slot(
    db: AsyncSession,
    *,
    business_id: UUID,
    service: str | None = None,
    when_label: str | None = None,
) -> WaitlistEntry | None:
    """Un créneau s'est libéré : signale le 1er inscrit compatible au salon.

    Marque l'entrée « notified » et crée une notification (cloche du dashboard) avec
    le contact du client et la prestation, pour un rappel prioritaire. Renvoie
    l'entrée prévenue, ou None si la file est vide / aucune entrée compatible.

    Note : l'envoi automatique au client (WhatsApp/Insta) viendra plus tard ; pour
    l'instant le salon est notifié et rappelle lui-même — c'est réel et exploitable.
    """
    waiting = (
        await db.execute(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.business_id == business_id,
                WaitlistEntry.status == "waiting",
            )
            .order_by(WaitlistEntry.created_at.asc())
        )
    ).scalars().all()

    match = next((e for e in waiting if _services_match(e.service, service)), None)
    if match is None:
        return None

    match.status = "notified"
    match.notified_at = datetime.now(UTC)

    who = match.customer_name or "un client"
    contact = f" ({match.customer_contact})" if match.customer_contact else ""
    svc_label = match.service or service or "une prestation"
    slot_txt = f" du {when_label}" if when_label else ""
    db.add(
        Notification(
            business_id=business_id,
            recipient=None,
            kind="waitlist_match",
            title="Place libérée — client en liste d'attente",
            body=(
                f"Le créneau{slot_txt} s'est libéré pour « {svc_label} ». "
                f"Recontacte en priorité {who}{contact}, en liste d'attente."
            ),
            conversation_id=match.conversation_id,
            meta={
                "waitlist_entry_id": str(match.id),
                "customer_id": str(match.customer_id) if match.customer_id else None,
                "conversation_id": str(match.conversation_id)
                if match.conversation_id
                else None,
                "service": match.service,
            },
        )
    )
    logger.info(
        "waitlist.notified",
        business_id=str(business_id),
        entry_id=str(match.id),
        service=service,
    )
    return match
