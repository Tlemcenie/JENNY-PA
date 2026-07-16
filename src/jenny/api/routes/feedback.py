"""feedback sur les réponses jenny."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.message import Message
from jenny.domain.models.message_feedback import MessageFeedback

logger = get_logger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


# schémas


class FeedbackPayload(BaseModel):
    message_id: UUID
    # validé par le schéma
    rating: Literal[1, -1] = Field(..., description="+1 (pouce haut) ou -1 (pouce bas)")
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackState(BaseModel):
    message_id: UUID
    rating: int | None = None  # None = pas encore évalué
    comment: str | None = None


class FeedbackMetrics(BaseModel):
    total_rated: int
    positive: int
    negative: int
    satisfaction_pct: float  # % d'avis positifs
    coverage_rated: int  # réponses évaluées
    responses_total: int  # total réponses jenny
    last_7_days: dict  # {"positive": int, "negative": int}
    recent_comments: list[dict]  # derniers retours négatifs
    recent_positive: list[dict]  # derniers retours positifs


# agrégation partagée


async def satisfaction_counts(
    db, business_id: UUID, *, days: int | None = None
) -> tuple[int, int, int, int, int, float]:
    """compteurs satisfaction en un scan."""
    now = datetime.now(UTC)
    since_7 = now - timedelta(days=7)
    scope = MessageFeedback.business_id == business_id
    if days is not None and days > 0:
        scope = scope & (MessageFeedback.created_at >= now - timedelta(days=days))

    def _count_if(cond) -> object:
        return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

    counts = (
        await db.execute(
            select(
                func.count(),
                _count_if(MessageFeedback.rating == 1),
                _count_if(MessageFeedback.rating == -1),
                _count_if((MessageFeedback.rating == 1) & (MessageFeedback.created_at >= since_7)),
                _count_if((MessageFeedback.rating == -1) & (MessageFeedback.created_at >= since_7)),
            ).where(scope)
        )
    ).one()
    total, positive, negative, pos_7, neg_7 = (int(c or 0) for c in counts)
    pct = round(100.0 * positive / total, 1) if total else 0.0
    return total, positive, negative, pos_7, neg_7, pct


# routes


@router.post("", response_model=FeedbackState)
async def submit_feedback(
    payload: FeedbackPayload, db: DbSession, principal: CurrentUser
) -> FeedbackState:
    """enregistre ou maj l'avis."""
    msg = await db.get(Message, payload.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message introuvable.")

    # isolation multi-tenant
    if principal.business_id is None or msg.business_id != principal.business_id:
        raise HTTPException(status_code=403, detail="Message hors de votre périmètre.")

    # seulement les réponses sortantes
    if msg.direction != "outbound":
        raise HTTPException(status_code=422, detail="Seules les réponses de Jenny sont évaluables.")

    existing = await db.scalar(
        select(MessageFeedback).where(MessageFeedback.message_id == payload.message_id)
    )
    # détecte le passage en négatif
    was_negative = existing is not None and existing.rating == -1
    if existing is None:
        existing = MessageFeedback(
            message_id=payload.message_id,
            conversation_id=msg.conversation_id,
            business_id=msg.business_id,
            rating=payload.rating,
            comment=payload.comment,
        )
        db.add(existing)
    else:
        existing.rating = payload.rating
        # on garde le commentaire
        if payload.comment is not None:
            existing.comment = payload.comment
    try:
        await db.commit()
    except IntegrityError:
        # course : on rejoue en update
        await db.rollback()
        existing = await db.scalar(
            select(MessageFeedback).where(MessageFeedback.message_id == payload.message_id)
        )
        if existing is None:  # pragma: no cover
            raise HTTPException(status_code=409, detail="Conflit d'écriture, réessayez.") from None
        was_negative = existing.rating == -1
        existing.rating = payload.rating
        if payload.comment is not None:
            existing.comment = payload.comment
        await db.commit()
    logger.info("feedback.submit", message_id=str(payload.message_id), rating=payload.rating)

    # alerte gérant sur négatif
    if payload.rating == -1 and (not was_negative or payload.comment):
        await _notify_negative_feedback(db, msg, payload.comment)

    return FeedbackState(
        message_id=payload.message_id, rating=existing.rating, comment=existing.comment
    )


async def _notify_negative_feedback(db, msg: Message, comment: str | None) -> None:
    """notifie le gérant + SSE."""
    try:
        from jenny.services.notification_service import notify_and_publish

        preview = (msg.content_text or "")[:100]
        body = f"Réponse jugée « à revoir » : « {preview} »"
        if comment:
            body += f" — commentaire : « {comment[:120]} »"
        await notify_and_publish(
            db,
            business_id=msg.business_id,
            kind="feedback_negative",
            title="Une réponse de Jenny est à revoir 👎",
            body=body,
            conversation_id=msg.conversation_id,
            meta={"message_id": str(msg.id), "conversation_id": str(msg.conversation_id)},
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("feedback.notify_failed", error=str(exc))


@router.delete("/message/{message_id}", response_model=FeedbackState)
async def delete_message_feedback(
    message_id: UUID, db: DbSession, principal: CurrentUser
) -> FeedbackState:
    """annule l'avis d'un message."""
    if principal.business_id is None:
        raise HTTPException(status_code=403, detail="Message hors de votre périmètre.")
    fb = await db.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.business_id == principal.business_id,
        )
    )
    if fb is not None:
        await db.delete(fb)
        await db.commit()
        logger.info("feedback.delete", message_id=str(message_id))
    return FeedbackState(message_id=message_id, rating=None)


@router.get("/message/{message_id}", response_model=FeedbackState)
async def get_message_feedback(
    message_id: UUID, db: DbSession, principal: CurrentUser
) -> FeedbackState:
    """avis courant d'un message."""
    if principal.business_id is None:
        raise HTTPException(status_code=403, detail="Message hors de votre périmètre.")
    fb = await db.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.business_id == principal.business_id,
        )
    )
    if fb is None:
        return FeedbackState(message_id=message_id, rating=None)
    return FeedbackState(message_id=message_id, rating=fb.rating, comment=fb.comment)


async def _recent_feedback_context(db, bid: UUID, *, rating: int, limit: int) -> list[dict]:
    """derniers avis avec contexte."""
    rows = await db.execute(
        select(
            MessageFeedback.comment,
            MessageFeedback.created_at,
            Message.content_text,
            Message.conversation_id,
            Message.received_at,
        )
        .join(Message, Message.id == MessageFeedback.message_id)
        .where(MessageFeedback.business_id == bid, MessageFeedback.rating == rating)
        .order_by(MessageFeedback.created_at.desc())
        .limit(limit)
    )
    out: list[dict] = []
    for comment, ts, answer, conv_id, answered_at in rows.all():
        question = None
        if conv_id is not None and answered_at is not None:
            question = await db.scalar(
                select(Message.content_text)
                .where(
                    Message.conversation_id == conv_id,
                    Message.direction == "inbound",
                    Message.received_at <= answered_at,
                )
                .order_by(Message.received_at.desc())
                .limit(1)
            )
        out.append(
            {
                "comment": comment,
                "question": question,
                "answer": answer,
                "created_at": ts.isoformat(),
            }
        )
    return out


@router.get("/metrics", response_model=FeedbackMetrics)
async def feedback_metrics(
    db: DbSession,
    principal: CurrentUser,
    days: int | None = None,
) -> FeedbackMetrics:
    """métriques satisfaction du business."""
    bid = principal.business_id
    if bid is None:
        return FeedbackMetrics(
            total_rated=0,
            positive=0,
            negative=0,
            satisfaction_pct=0.0,
            coverage_rated=0,
            responses_total=0,
            last_7_days={"positive": 0, "negative": 0},
            recent_comments=[],
            recent_positive=[],
        )

    total, positive, negative, pos_7, neg_7, satisfaction = await satisfaction_counts(
        db, bid, days=days
    )

    resp_scope = [Message.business_id == bid, Message.direction == "outbound"]
    if days is not None and days > 0:
        resp_scope.append(Message.created_at >= datetime.now(UTC) - timedelta(days=days))
    responses_total = (
        await db.scalar(select(func.count()).select_from(Message).where(*resp_scope)) or 0
    )

    # derniers retours avec contexte
    recent_comments = await _recent_feedback_context(db, bid, rating=-1, limit=5)
    recent_positive = await _recent_feedback_context(db, bid, rating=1, limit=3)

    return FeedbackMetrics(
        total_rated=total,
        positive=positive,
        negative=negative,
        satisfaction_pct=satisfaction,
        coverage_rated=total,
        responses_total=responses_total,
        last_7_days={"positive": pos_7, "negative": neg_7},
        recent_positive=recent_positive,
        recent_comments=recent_comments,
    )
