"""Service d'apprentissage : mémoire client + lacunes de connaissance.

Côté DB (le moteur reste pur) :
- ``load_customer_facts`` : charge les faits durables d'un client pour les
  réinjecter dans le contexte du prochain message.
- ``persist_engine_signals`` : après chaque réponse de Jenny, enregistre les
  nouveaux faits client et, si Jenny n'a pas su répondre, ouvre/incrémente une
  « lacune de connaissance » et notifie l'équipe.

Tout est best-effort : une erreur de persistance ne casse jamais la conversation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from jenny.core.logging import get_logger
from jenny.domain.models.customer_fact import CustomerFact
from jenny.domain.models.knowledge_gap import KnowledgeGap
from jenny.domain.models.notification import Notification
from jenny.domain.models.pending_question import PendingQuestion
from jenny.engine.intelligence import normalize_question

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.engine.conversation_engine import EngineResponse

logger = get_logger(__name__)

_MAX_FACTS_INJECTED = 8


async def load_customer_facts(
    db: AsyncSession, business_id: UUID, customer_id: UUID | None
) -> list[str]:
    """Charge les faits durables connus sur un client (pour le contexte LLM)."""
    if customer_id is None:
        return []
    try:
        rows = (
            await db.execute(
                select(CustomerFact.fact)
                .where(
                    CustomerFact.business_id == business_id,
                    CustomerFact.customer_id == customer_id,
                )
                .order_by(CustomerFact.confidence.desc(), CustomerFact.updated_at.desc())
                .limit(_MAX_FACTS_INJECTED)
            )
        ).all()
        return [r[0] for r in rows]
    except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
        logger.warning("learning.load_facts_error", error=str(exc))
        return []


async def load_customer_context(
    db: AsyncSession, business_id: UUID, customer_id: UUID | None
) -> list[str]:
    """Contexte client pour le LLM : « client de retour » (nom + dernière visite) PUIS faits.

    Permet à Jenny de saluer un client connu par son prénom et de lui proposer
    « comme la dernière fois ? ». Best-effort : repli sur les seuls faits durables.
    """
    facts = await load_customer_facts(db, business_id, customer_id)
    if customer_id is None:
        return facts
    extra: list[str] = []
    try:
        from jenny.domain.models.appointment import Appointment
        from jenny.domain.models.customer import Customer

        cust = await db.get(Customer, customer_id)
        if cust is not None and (cust.full_name or "").strip():
            first_name = cust.full_name.strip().split()[0]
            extra.append(
                f"Ce client s'appelle {first_name} — tu peux l'appeler par son prénom, "
                "naturellement (une fois suffit, n'en fais pas trop)."
            )
        last = (
            await db.execute(
                select(Appointment)
                .where(
                    Appointment.business_id == business_id,
                    Appointment.customer_id == customer_id,
                    Appointment.status.notin_(["cancelled", "blocked"]),
                    Appointment.start_at < datetime.now(UTC),
                )
                .order_by(Appointment.start_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last is not None:
            extra.append(
                f"Client déjà venu — dernière prestation : « {last.title} ». Tu peux "
                "lui proposer la même (« comme la dernière fois ? ») si pertinent."
            )
    except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
        logger.warning("learning.load_context_error", error=str(exc))
    return extra + facts


async def _record_facts(
    db: AsyncSession,
    *,
    business_id: UUID,
    customer_id: UUID,
    conversation_id: UUID | None,
    facts: list[dict],
) -> int:
    """Enregistre les nouveaux faits (dédupliqués par empreinte)."""
    now = datetime.now(UTC)
    added = 0
    for f in facts:
        text = (f.get("fact") or "").strip()
        if not text:
            continue
        key = normalize_question(text, max_len=200)
        existing = (
            await db.execute(
                select(CustomerFact).where(
                    CustomerFact.business_id == business_id,
                    CustomerFact.customer_id == customer_id,
                    CustomerFact.fact_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.last_seen_at = now
            continue
        db.add(
            CustomerFact(
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                fact=text,
                fact_key=key,
                kind=f.get("kind") or "other",
                source="conversation",
                last_seen_at=now,
            )
        )
        added += 1
    return added


async def _record_gap(
    db: AsyncSession,
    *,
    business_id: UUID,
    customer_id: UUID | None,
    conversation_id: UUID | None,
    channel: str | None,
    intent: str | None,
    question: str,
) -> bool:
    """Ouvre ou incrémente une lacune. Renvoie True si une NOUVELLE lacune est créée."""
    key = normalize_question(question)
    if not key:
        return False
    now = datetime.now(UTC)
    existing = (
        await db.execute(
            select(KnowledgeGap).where(
                KnowledgeGap.business_id == business_id,
                KnowledgeGap.question_key == key,
                KnowledgeGap.status == "open",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.occurrences = (existing.occurrences or 1) + 1
        existing.last_seen_at = now
        return False
    db.add(
        KnowledgeGap(
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            question=question,
            question_key=key,
            channel=channel,
            intent=intent,
            status="open",
            occurrences=1,
            last_seen_at=now,
        )
    )
    # Notifie l'équipe qu'une question est restée sans réponse.
    db.add(
        Notification(
            business_id=business_id,
            recipient=None,
            kind="knowledge_gap",
            title="Une question est restée sans réponse",
            body=question[:200],
            conversation_id=conversation_id,
            meta={"intent": intent, "channel": channel},
        )
    )
    return True


async def _record_pending_question(
    db: AsyncSession,
    *,
    business_id: UUID,
    customer_id: UUID | None,
    conversation_id: UUID,
    question: str,
) -> None:
    """Crée une question en attente pour la conversation (si pas déjà ouverte)."""
    existing = (
        await db.execute(
            select(PendingQuestion.id).where(
                PendingQuestion.conversation_id == conversation_id,
                PendingQuestion.status == "open",
                PendingQuestion.question == question,
            )
        )
    ).first()
    if existing is not None:
        return
    db.add(
        PendingQuestion(
            business_id=business_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            question=question,
            origin="customer",
            status="open",
        )
    )


async def persist_engine_signals(
    db: AsyncSession,
    *,
    business_id: UUID,
    customer_id: UUID | None,
    conversation_id: UUID | None,
    channel: str | None,
    result: EngineResponse,
) -> None:
    """Persiste faits client + lacune de connaissance issus d'une réponse moteur.

    Best-effort : toute erreur est avalée (loggée) pour ne pas casser le chat.
    """
    try:
        touched = False
        if customer_id is not None and result.extracted_facts:
            added = await _record_facts(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                facts=result.extracted_facts,
            )
            touched = touched or added > 0
        if result.knowledge_gap and result.gap_question:
            # Crée une nouvelle lacune OU incrémente une existante : dans les deux
            # cas il y a une écriture à committer.
            await _record_gap(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                channel=channel,
                intent=result.intent,
                question=result.gap_question,
            )
            # Dans une vraie conversation, on garde aussi la question DE CÔTÉ pour
            # que le commerçant y réponde directement au client (vue conversation).
            if conversation_id is not None:
                await _record_pending_question(
                    db,
                    business_id=business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    question=result.gap_question,
                )
            touched = True
        if touched:
            await db.commit()
    except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
        await db.rollback()
        logger.warning("learning.persist_error", error=str(exc))
