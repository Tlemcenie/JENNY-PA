"""Tâches asynchrones ARQ.

Définit les tâches de fond exécutées par le worker ARQ :
- normalisation de messages,
- traitement / classification ML,
- génération de réponses,
- synchronisation connecteurs.

ARQ utilise Redis comme broker (déjà dans la stack).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from arq.connections import RedisSettings
from arq.cron import cron

from jenny.connectors.email.imap_utils import fetch_unseen_mails_sync, parse_mime_to_email_payload
from jenny.connectors.email.service import EmailConnectorService
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.message_event_repo import MessageEventRepository
from jenny.db.repositories.message_repo import MessageRepository
from jenny.db.session import async_session_factory
from jenny.services.text_clean import clean_message_text, detect_language_safe

logger = get_logger(__name__)


def _intent_from_checkpoint(text: str) -> tuple[str | None, float]:
    """Charge le prédicteur intent si checkpoint présent (léger)."""
    ckpt = Path("checkpoints/intent/best_model.pt")
    if not ckpt.exists():
        return None, 0.0
    try:
        from ml.models.intent.predict import IntentPredictor

        predictor = IntentPredictor.from_checkpoint(str(ckpt))
        result = predictor.predict_multi(text)
        primary = result.get("primary_intent")
        conf = float(result.get("primary_confidence") or 0.0)
        return primary, conf
    except Exception as e:
        logger.warning("task.process_message.intent_failed", error=str(e))
        return None, 0.0


async def normalize_message(ctx: dict[str, Any], message_id: str) -> dict[str, str]:
    """Normalise un message après ingestion."""
    logger.info("task.normalize_message.start", message_id=message_id)
    mid = UUID(message_id)

    async with async_session_factory() as session, session.begin():
        repo = MessageRepository(session)
        events = MessageEventRepository(session)
        msg = await repo.get_by_id(mid)
        if msg is None:
            logger.warning("task.normalize_message.not_found", message_id=message_id)
            return {"status": "skipped", "reason": "not_found"}

        msg.status = "normalizing"
        await session.flush()

        cleaned = clean_message_text(msg.content_text)
        lang = detect_language_safe(cleaned) or msg.language

        msg.cleaned_text = cleaned
        msg.language = lang
        msg.status = "normalized"
        msg.normalized_at = datetime.now(UTC)

        await events.log_event(
            message_id=mid,
            event_type="normalized",
            detail="Texte nettoyé et langue détectée",
            payload={"language": lang},
        )

    redis = ctx.get("redis")
    if redis is not None:
        await redis.enqueue_job("process_message", message_id)
    else:
        from jenny.workers.queue import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job("process_message", message_id)

    logger.info("task.normalize_message.done", message_id=message_id)
    return {"status": "normalized", "message_id": message_id}


async def process_message(ctx: dict[str, Any], message_id: str) -> dict[str, str]:
    """Enrichit le message (intent léger) après normalisation."""
    logger.info("task.process_message.start", message_id=message_id)
    mid = UUID(message_id)

    text_for_ml = ""
    async with async_session_factory() as session, session.begin():
        repo = MessageRepository(session)
        events = MessageEventRepository(session)
        msg = await repo.get_by_id(mid)
        if msg is None:
            return {"status": "skipped", "reason": "not_found"}

        msg.status = "processing"
        await session.flush()

        text_for_ml = (msg.cleaned_text or msg.content_text or "").strip()
        intent_label, conf = (None, 0.0)
        if text_for_ml:
            intent_label, conf = _intent_from_checkpoint(text_for_ml)

        if intent_label:
            msg.intent_label = intent_label
        if conf > 0:
            msg.priority = max(1, min(10, int(5 + conf * 5)))

        msg.status = "normalized"
        await events.log_event(
            message_id=mid,
            event_type="classified",
            detail="Intent ML (worker)",
            payload={"intent": intent_label, "confidence": conf},
        )

    logger.info("task.process_message.done", message_id=message_id)
    return {"status": "processed", "message_id": message_id}


async def sync_connector(ctx: dict[str, Any], connector_name: str) -> dict[str, str]:
    """Synchronise les messages depuis un connecteur externe (polling)."""
    logger.info("task.sync_connector.start", connector=connector_name)
    return {"status": "synced", "connector": connector_name}


async def poll_imap_mailbox(ctx: dict[str, Any]) -> dict[str, str]:
    """Lit la boîte IMAP (non lus), ingère et enfile la normalisation."""
    settings = get_settings()
    bid_str = (settings.imap_business_id or settings.default_business_id or "").strip()
    if (
        not settings.imap_host
        or not settings.imap_user
        or not settings.imap_password
        or not bid_str
    ):
        return {"status": "skipped", "reason": "imap_or_business_not_configured"}

    business_id = UUID(bid_str)
    try:
        raw_list = await asyncio.to_thread(
            fetch_unseen_mails_sync,
            settings.imap_host,
            settings.imap_user,
            settings.imap_password,
            settings.imap_mailbox,
            settings.imap_use_ssl,
        )
    except Exception as e:
        logger.error("task.poll_imap_mailbox.imap_error", error=str(e))
        return {"status": "error", "reason": str(e)}

    n = 0
    for raw in raw_list:
        payload = parse_mime_to_email_payload(raw, settings.imap_user)
        if not payload:
            continue
        async with async_session_factory() as session, session.begin():
            svc = EmailConnectorService(session)
            result = await svc.handle_email(payload, business_id)
        mid = str(result.message.id)
        redis = ctx.get("redis")
        if redis is not None:
            await redis.enqueue_job("normalize_message", mid)
        else:
            from jenny.workers.queue import get_arq_pool

            pool = await get_arq_pool()
            await pool.enqueue_job("normalize_message", mid)
        n += 1

    logger.info("task.poll_imap_mailbox.done", ingested=n)
    return {"status": "ok", "ingested": str(n)}


async def sweep_conversations(ctx: dict[str, Any]) -> dict[str, str]:
    """Cron (chaque minute) : dé-snooze les conversations dues et escalade les
    clients mécontents restés sans réponse au-delà du SLA (#5/#6).

    - Dé-snooze : ``snoozed_until`` échu → on l'efface (la conversation
      réapparaît dans la vue active) et on notifie l'agent qui l'avait reportée.
    - Auto-escalade : conversation au sentiment négatif, non escaladée, dont le
      dernier message est entrant (client en attente) depuis plus que le SLA du
      business → on lève le drapeau, on remonte la priorité et on notifie.

    Tourne dans le process worker : on persiste des notifications en base (la
    cloche du dashboard les relève) plutôt que de pousser sur le bus SSE
    in-process de l'API (autre process).
    """
    from sqlalchemy import select

    from jenny.domain.models.business import Business
    from jenny.domain.models.conversation import Conversation
    from jenny.domain.models.message import Message
    from jenny.domain.models.notification import Notification

    now = datetime.now(UTC)
    unsnoozed = 0
    escalated = 0
    reminded = 0
    day_reminded = 0
    review_asked = 0
    rebook_nudged = 0
    async with async_session_factory() as session, session.begin():
        # 1. Dé-snooze des conversations dont l'échéance est passée.
        due = (
            await session.execute(
                select(Conversation).where(
                    Conversation.snoozed_until.is_not(None),
                    Conversation.snoozed_until <= now,
                )
            )
        ).scalars().all()
        for conv in due:
            conv.snoozed_until = None
            session.add(
                Notification(
                    business_id=conv.business_id,
                    recipient=conv.assigned_to,
                    kind="snooze_due",
                    title="Conversation à reprendre",
                    body=conv.last_message_preview,
                    conversation_id=conv.id,
                    meta={"reason": "snooze_elapsed"},
                )
            )
            unsnoozed += 1

        # 2. Escalade des clients mécontents sans réponse au-delà du SLA.
        last_direction = (
            select(Message.direction)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = (
            await session.execute(
                select(Conversation, Business.sla_minutes)
                .join(Business, Business.id == Conversation.business_id)
                .where(
                    Conversation.status.not_in(["closed", "archived"]),
                    Conversation.sentiment == "negative",
                    Conversation.is_escalated.is_(False),
                    Conversation.last_message_at.is_not(None),
                    last_direction == "inbound",
                )
            )
        ).all()
        for conv, sla in rows:
            lma = conv.last_message_at
            if lma.tzinfo is None:
                lma = lma.replace(tzinfo=UTC)
            waited = (now - lma).total_seconds() / 60
            if waited >= (sla or 30):
                conv.is_escalated = True
                if conv.priority_level in (None, "low", "medium"):
                    conv.priority_level = "high"
                session.add(
                    Notification(
                        business_id=conv.business_id,
                        recipient=conv.assigned_to,
                        kind="escalated",
                        title="Escalade : client mécontent sans réponse",
                        body=f"En attente depuis {int(waited)} min",
                        conversation_id=conv.id,
                        meta={"reason": "negative_overdue", "waited_minutes": int(waited)},
                    )
                )
                escalated += 1

        # 3+4. Rappels de RDV — délais CONFIGURABLES par salon (#90) :
        # rappel « imminent » (reminder_lead_minutes) et « la veille »
        # (day_reminder_lead_hours), lus sur le business de chaque RDV.
        from datetime import timedelta

        from sqlalchemy import or_

        from jenny.domain.models.appointment import Appointment

        horizon = now + timedelta(days=30)
        rem_rows = (
            await session.execute(
                select(
                    Appointment,
                    Business.reminder_lead_minutes,
                    Business.day_reminder_lead_hours,
                )
                .join(Business, Business.id == Appointment.business_id)
                .where(
                    Appointment.status.not_in(["cancelled", "completed", "blocked", "no_show"]),
                    Appointment.start_at >= now,
                    Appointment.start_at <= horizon,
                    or_(
                        Appointment.reminder_sent_at.is_(None),
                        Appointment.day_reminder_sent_at.is_(None),
                    ),
                )
            )
        ).all()
        for a, lead_min, lead_hours in rem_rows:
            lead_min = int(lead_min or 60)
            lead_hours = int(lead_hours or 24)
            start = a.start_at if a.start_at.tzinfo else a.start_at.replace(tzinfo=UTC)
            delta_min = (start - now).total_seconds() / 60
            loc = f" · {a.location}" if a.location else ""
            if a.reminder_sent_at is None and 0 <= delta_min <= lead_min:
                a.reminder_sent_at = now
                session.add(
                    Notification(
                        business_id=a.business_id,
                        recipient=a.created_by,
                        kind="appointment_reminder",
                        title=f"RDV bientôt : {a.title}",
                        body=f"À {start:%H:%M}{loc}",
                        conversation_id=a.conversation_id,
                        meta={"appointment_id": str(a.id)},
                    )
                )
                reminded += 1
            elif a.day_reminder_sent_at is None and lead_min < delta_min <= lead_hours * 60:
                a.day_reminder_sent_at = now
                session.add(
                    Notification(
                        business_id=a.business_id,
                        recipient=a.created_by,
                        kind="appointment_reminder_day",
                        title=f"Rappel demain : {a.title}",
                        body=f"{start:%d/%m à %H:%M}{loc}",
                        conversation_id=a.conversation_id,
                        meta={"appointment_id": str(a.id)},
                    )
                )
                day_reminded += 1

        # 5. Avis post-RDV : prestation honorée et terminée récemment (< 48h),
        # avis pas encore demandé → on invite le salon à solliciter un retour.
        review_window_start = now - timedelta(hours=48)
        done_appts = (
            await session.execute(
                select(Appointment).where(
                    Appointment.review_request_sent_at.is_(None),
                    Appointment.status.in_(["completed", "confirmed", "scheduled"]),
                    Appointment.end_at <= now,
                    Appointment.end_at >= review_window_start,
                )
            )
        ).scalars().all()
        for a in done_appts:
            a.review_request_sent_at = now
            session.add(
                Notification(
                    business_id=a.business_id,
                    recipient=a.created_by,
                    kind="review_request",
                    title="Demander un avis",
                    body=f"« {a.title} » est terminé : pensez à demander un avis au client.",
                    conversation_id=a.conversation_id,
                    meta={"appointment_id": str(a.id), "customer_id": str(a.customer_id)
                          if a.customer_id else None},
                )
            )
            review_asked += 1

        # 6. Relance de re-réservation : dernier RDV honoré il y a 6-9 semaines,
        # client identifié, AUCUN RDV à venir → on suggère de le relancer (fidélisation).
        rebook_old = now - timedelta(days=63)
        rebook_due = now - timedelta(days=42)
        stale_appts = (
            await session.execute(
                select(Appointment).where(
                    Appointment.rebook_reminder_sent_at.is_(None),
                    Appointment.status.in_(["completed", "confirmed"]),
                    Appointment.customer_id.is_not(None),
                    Appointment.end_at <= rebook_due,
                    Appointment.end_at >= rebook_old,
                )
            )
        ).scalars().all()
        for a in stale_appts:
            # Pas de relance si le client a déjà un RDV à venir.
            upcoming = (
                await session.execute(
                    select(Appointment.id).where(
                        Appointment.business_id == a.business_id,
                        Appointment.customer_id == a.customer_id,
                        Appointment.status.not_in(["cancelled", "blocked"]),
                        Appointment.start_at >= now,
                    ).limit(1)
                )
            ).first()
            a.rebook_reminder_sent_at = now  # marqué dans tous les cas (anti-rebalayage)
            if upcoming is not None:
                continue
            session.add(
                Notification(
                    business_id=a.business_id,
                    recipient=a.created_by,
                    kind="rebook_reminder",
                    title="Client à relancer",
                    body=f"Dernier RDV « {a.title} » il y a plus de 6 semaines — "
                    "proposez-lui un nouveau créneau.",
                    conversation_id=a.conversation_id,
                    meta={"appointment_id": str(a.id), "customer_id": str(a.customer_id)},
                )
            )
            rebook_nudged += 1

    if unsnoozed or escalated or reminded or day_reminded or review_asked or rebook_nudged:
        logger.info(
            "task.sweep_conversations.done",
            unsnoozed=unsnoozed,
            escalated=escalated,
            reminded=reminded,
            day_reminded=day_reminded,
            review_asked=review_asked,
            rebook_nudged=rebook_nudged,
        )
    return {
        "unsnoozed": str(unsnoozed),
        "escalated": str(escalated),
        "reminded": str(reminded),
        "day_reminded": str(day_reminded),
        "review_asked": str(review_asked),
        "rebook_nudged": str(rebook_nudged),
    }


async def startup(ctx: dict[str, Any]) -> None:
    """Initialisation au démarrage du worker."""
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Nettoyage à l'arrêt du worker."""
    logger.info("worker.shutdown")


def _imap_cron_minutes() -> set[int]:
    s = get_settings()
    step = max(1, min(29, max(1, s.imap_poll_seconds // 60)))
    return set(range(0, 60, step))


class WorkerSettings:
    """Configuration du worker ARQ."""

    functions: ClassVar[list] = [
        normalize_message,
        process_message,
        sync_connector,
        poll_imap_mailbox,
        sweep_conversations,
    ]
    on_startup = startup
    on_shutdown = shutdown

    cron_jobs: ClassVar[list] = [
        cron(poll_imap_mailbox, minute=_imap_cron_minutes()),
        # Balaye chaque minute : dé-snooze + auto-escalade (#5/#6).
        cron(sweep_conversations, minute=set(range(60))),
    ]

    # arq lit cet attribut via settings_cls.__dict__ et le passe TEL QUEL à
    # create_pool : ce doit donc être une instance RedisSettings, pas une
    # méthode (un @staticmethod serait passé sans être appelé → crash).
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().redis_url)
