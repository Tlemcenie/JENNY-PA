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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from jenny.core.logging import get_logger
from jenny.domain.models.notification import Notification
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.services.freed_slots import take_freed_slot

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


async def _recipient(
    db: AsyncSession, business_id: UUID, entry: WaitlistEntry
) -> tuple[UUID | None, str | None, str | None]:
    """(fiche, clé d'offre, nom) de l'inscrit."""
    from jenny.domain.models.conversation import Conversation
    from jenny.domain.models.customer import Customer
    from jenny.services.gap_filler import recipient_key

    cid = entry.customer_id
    conv = None
    if entry.conversation_id is not None:
        conv = await db.get(Conversation, entry.conversation_id)
        if conv is not None and conv.business_id != business_id:
            conv = None
    if cid is None and conv is not None:
        cid = conv.customer_id
    if cid is not None:
        cust = await db.get(Customer, cid)
        if cust is None or cust.business_id != business_id:
            return None, None, None
        return cid, recipient_key(cid, None), cust.full_name
    if conv is None:
        # personne à joindre
        return None, None, None
    return None, recipient_key(None, conv.id), None


async def _trace_offer(
    db: AsyncSession,
    *,
    business_id: UUID,
    entry: WaitlistEntry,
    customer_id: UUID | None,
    key: str,
    slot_start: datetime,
    minutes: int,
    label: str | None,
) -> UUID | None:
    """Note l'offre (une fois), sinon None."""
    from uuid import uuid4

    from jenny.domain.models.campaign import SlotOffer
    from jenny.services.availability import MAX_SERVICE_MINUTES
    from jenny.services.campaigns import insert_once

    offer_id = uuid4()
    values = {
        "id": offer_id,
        "business_id": business_id,
        "customer_id": customer_id,
        "conversation_id": entry.conversation_id,
        "waitlist_entry_id": entry.id,
        "recipient_key": key,
        "slot_start": slot_start if slot_start.tzinfo else slot_start.replace(tzinfo=UTC),
        "duration_minutes": max(5, min(MAX_SERVICE_MINUTES, int(minutes))),
        "service": label[:120] if label else None,
        "source": "waitlist",
        "reason": "annulation",
    }
    keys = ["business_id", "recipient_key", "slot_start"]
    if not await insert_once(db, SlotOffer, values, keys):
        return None
    return offer_id


async def _really_free(
    db: AsyncSession,
    business_id: UUID,
    slot_start: datetime | None,
    minutes: int | None,
    staff_id: UUID | None,
) -> bool:
    """Place vraiment reprenable ?"""
    from jenny.services.availability import freed_is_bookable, load_staff_pool

    pool = await load_staff_pool(db, business_id)
    if slot_start is None:
        # heure inconnue : coiffeur seul
        return staff_id is None or not pool.has_staff or pool.get(staff_id) is not None
    start = slot_start if slot_start.tzinfo else slot_start.replace(tzinfo=UTC)
    end = start + timedelta(minutes=max(5, int(minutes or 30)))
    return await freed_is_bookable(db, business_id, start, end, staff_id=staff_id, pool=pool)


async def notify_waitlist_for_freed_slot(
    db: AsyncSession,
    *,
    business_id: UUID,
    service: str | None = None,
    when_label: str | None = None,
    slot_start: datetime | None = None,
    duration_minutes: int | None = None,
    staff_id: UUID | None = None,
) -> WaitlistEntry | None:
    """Un créneau s'est libéré : signale le 1er inscrit compatible au salon.

    Marque l'entrée « notified » et crée une notification (cloche du dashboard) avec
    le contact du client et la prestation, pour un rappel prioritaire. Renvoie
    l'entrée prévenue, ou None si la file est vide / aucune entrée compatible.

    Le client reçoit aussi un message (offre : plafond anti-spam), tracé dans
    slot_offers pour que le gap filler ne repropose pas la place. Si
    personne n'attend, une passe de remplissage d'agenda est lancée.
    ``service`` peut être le titre libre du RDV : il n'est jamais envoyé
    tel quel au client.

    Rien ne part si la place ne resservira pas (``staff_id`` = coiffeur
    du RDV libéré : en pause, il ne libère rien pour les autres).
    """
    if slot_start is None:
        # lu avant tout flush
        freed = take_freed_slot(db, business_id)
        if freed is not None:
            slot_start, duration_minutes = freed[0], duration_minutes or freed[1]

    if not await _really_free(db, business_id, slot_start, duration_minutes, staff_id):
        logger.info("waitlist.freed_not_bookable", business_id=str(business_id))
        return None

    waiting = (
        (
            await db.execute(
                select(WaitlistEntry)
                .where(
                    WaitlistEntry.business_id == business_id,
                    WaitlistEntry.status == "waiting",
                )
                .order_by(WaitlistEntry.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    match = next((e for e in waiting if _services_match(e.service, service)), None)
    if match is None:
        # personne n'attend : passe agenda
        from jenny.services.gap_filler import schedule_after_change

        await schedule_after_change(db, business_id)
        return None

    match.status = "notified"
    match.notified_at = datetime.now(UTC)

    contact = f" ({match.customer_contact})" if match.customer_contact else ""
    # pour le gérant seulement
    svc_label = match.service or service or "une prestation"
    slot_txt = f" du {when_label}" if when_label else ""

    from jenny.domain.models.business import Business
    from jenny.notifications.outbound import notify_customer
    from jenny.services.prestation_service import find_prestation, load_active_prestations

    prestations = await load_active_prestations(db, business_id)
    # ses propres mots
    own = (match.service or "").strip()[:60] or None
    hit = find_prestation(prestations, own or service or "") if prestations else None
    # jamais le titre libre
    client_label = own or (hit.name[:60] if hit is not None and hit.name else None)
    if duration_minutes is None:
        duration_minutes = int(hit.duration_minutes) if hit and hit.duration_minutes else 30

    cid, key, fiche_name = await _recipient(db, business_id, match)
    who = match.customer_name or fiche_name or "un client"
    offer_id = None
    already = False
    if slot_start is not None and key is not None:
        offer_id = await _trace_offer(
            db,
            business_id=business_id,
            entry=match,
            customer_id=cid,
            key=key,
            slot_start=slot_start,
            minutes=duration_minutes,
            label=client_label,
        )
        # déjà proposé à elle
        already = offer_id is None

    canal = None
    if not already:
        biz = await db.get(Business, business_id)
        salon_txt = f"de {biz.name}" if biz is not None and biz.name else "du salon"
        svc_txt = f" pour « {client_label} »" if client_label else ""
        # message client, plafond compris
        canal = await notify_customer(
            db,
            business_id=business_id,
            customer_id=cid,
            conversation_id=match.conversation_id,
            text=(
                f"Ici Jenny, l'assistante virtuelle {salon_txt}. "
                f"Bonne nouvelle : un créneau{slot_txt} vient de se libérer{svc_txt}. "
                "Ça vous intéresse ? Répondez-moi et je vous le bloque. "
                "STOP pour ne plus recevoir d'offres."
            ),
            subject="Un créneau s'est libéré",
            commercial=True,
        )
    if canal and offer_id is not None:
        from sqlalchemy import update

        from jenny.domain.models.campaign import SlotOffer

        await db.execute(
            update(SlotOffer)
            .where(SlotOffer.id == offer_id)
            .values(channel=canal, sent_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
    if canal:
        auto = f" Jenny l'a déjà prévenu par {canal}."
    elif already:
        auto = " Pas de message auto (ce créneau lui a déjà été proposé)."
    else:
        auto = " Pas de message auto (déjà sollicité cette semaine, STOP ou injoignable)."
    db.add(
        Notification(
            business_id=business_id,
            recipient=None,
            kind="waitlist_match",
            title="Place libérée — client en liste d'attente",
            body=(
                f"Le créneau{slot_txt} s'est libéré pour « {svc_label} ». "
                f"Recontacte en priorité {who}{contact}, en liste d'attente.{auto}"
            ),
            conversation_id=match.conversation_id,
            meta={
                "waitlist_entry_id": str(match.id),
                "customer_id": str(match.customer_id) if match.customer_id else None,
                "conversation_id": str(match.conversation_id) if match.conversation_id else None,
                "service": match.service,
                "client_notified_via": canal,
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
