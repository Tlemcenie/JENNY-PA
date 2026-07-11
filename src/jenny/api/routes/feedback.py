"""Feedback utilisateur sur les réponses de Jenny (pouce ↑ / pouce ↓).

Endpoints :
- ``POST /feedback``            → enregistre (ou met à jour) l'avis sur un message
- ``GET  /feedback/message/{id}`` → avis courant pour un message (hydrate l'UI)
- ``GET  /feedback/metrics``   → métriques de satisfaction agrégées du business

Simple par choix produit : une évaluation binaire (+1 / -1), pas d'étoiles.
"""

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


# ── Schémas ──


class FeedbackPayload(BaseModel):
    message_id: UUID
    # Contraint dans le schéma (et donc l'OpenAPI) plutôt que revalidé à la main.
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
    satisfaction_pct: float  # part de 👍 parmi les avis (0 a 100)
    coverage_rated: int  # nombre de réponses évaluées (= total_rated)
    responses_total: int  # nombre total de réponses Jenny (messages sortants)
    last_7_days: dict  # {"positive": int, "negative": int}
    recent_comments: list[dict]  # derniers commentaires négatifs (à améliorer)


# ── Agrégation partagée ──


async def satisfaction_counts(db, business_id: UUID) -> tuple[int, int, int, int, int, float]:
    """Compteurs de satisfaction d'un business, en UN SEUL scan de la table.

    Renvoie ``(total, positifs, négatifs, positifs_7j, négatifs_7j, pct)``.
    Source de vérité UNIQUE du « % de satisfaction » : utilisée par
    ``/feedback/metrics`` (carte Satisfaction) ET ``/jenny/metrics`` (page
    Efficacité) pour que les deux surfaces affichent le même chiffre.
    """
    since = datetime.now(UTC) - timedelta(days=7)

    def _count_if(cond) -> object:
        return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

    counts = (
        await db.execute(
            select(
                func.count(),
                _count_if(MessageFeedback.rating == 1),
                _count_if(MessageFeedback.rating == -1),
                _count_if((MessageFeedback.rating == 1) & (MessageFeedback.created_at >= since)),
                _count_if((MessageFeedback.rating == -1) & (MessageFeedback.created_at >= since)),
            ).where(MessageFeedback.business_id == business_id)
        )
    ).one()
    total, positive, negative, pos_7, neg_7 = (int(c or 0) for c in counts)
    pct = round(100.0 * positive / total, 1) if total else 0.0
    return total, positive, negative, pos_7, neg_7, pct


# ── Routes ──


@router.post("", response_model=FeedbackState)
async def submit_feedback(
    payload: FeedbackPayload, db: DbSession, principal: CurrentUser
) -> FeedbackState:
    """Enregistre ou met à jour l'avis 👍/👎 d'un message (réponse de Jenny)."""
    msg = await db.get(Message, payload.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message introuvable.")

    # Sécurité multi-tenant : on n'évalue que les messages de son propre business.
    # Un principal sans business n'a de périmètre sur aucun message.
    if principal.business_id is None or msg.business_id != principal.business_id:
        raise HTTPException(status_code=403, detail="Message hors de votre périmètre.")

    # Seules les réponses de Jenny (sortantes) sont évaluables : noter un message
    # client fausserait la satisfaction (responses_total ne compte que l'outbound).
    if msg.direction != "outbound":
        raise HTTPException(status_code=422, detail="Seules les réponses de Jenny sont évaluables.")

    existing = await db.scalar(
        select(MessageFeedback).where(MessageFeedback.message_id == payload.message_id)
    )
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
        # Un simple re-clic 👍/👎 (sans texte) ne doit pas effacer un commentaire
        # déjà saisi — on n'écrase que si un commentaire est explicitement fourni.
        if payload.comment is not None:
            existing.comment = payload.comment
    try:
        await db.commit()
    except IntegrityError:
        # Deux clics quasi simultanés sur le même message : les deux requêtes
        # passent le SELECT sans trouver de ligne, la seconde viole la contrainte
        # unique. On rejoue en UPDATE sur la ligne gagnante.
        await db.rollback()
        existing = await db.scalar(
            select(MessageFeedback).where(MessageFeedback.message_id == payload.message_id)
        )
        if existing is None:  # pragma: no cover - course perdue ET ligne disparue
            raise HTTPException(status_code=409, detail="Conflit d'écriture, réessayez.") from None
        existing.rating = payload.rating
        if payload.comment is not None:
            existing.comment = payload.comment
        await db.commit()
    logger.info("feedback.submit", message_id=str(payload.message_id), rating=payload.rating)
    return FeedbackState(
        message_id=payload.message_id, rating=existing.rating, comment=existing.comment
    )


@router.get("/message/{message_id}", response_model=FeedbackState)
async def get_message_feedback(
    message_id: UUID, db: DbSession, principal: CurrentUser
) -> FeedbackState:
    """Renvoie l'avis courant pour un message (ou rating=None si aucun).

    Scopé au business courant : on ne lit jamais l'avis d'un message appartenant
    à une autre entreprise (isolation multi-tenant). Même règle que le POST :
    un principal sans business n'a de périmètre sur aucun message.
    """
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


@router.get("/metrics", response_model=FeedbackMetrics)
async def feedback_metrics(db: DbSession, principal: CurrentUser) -> FeedbackMetrics:
    """Métriques de satisfaction des réponses de Jenny pour le business courant."""
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
        )

    total, positive, negative, pos_7, neg_7, satisfaction = await satisfaction_counts(db, bid)

    responses_total = (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.business_id == bid, Message.direction == "outbound")
        )
        or 0
    )

    # Dernières réponses jugées « à revoir » : on renvoie le contexte complet
    # (question du client + réponse de Jenny + commentaire) pour que le gérant
    # voie exactement QUOI améliorer — c'est ça qui rend le 👎 actionnable.
    rows = await db.execute(
        select(
            MessageFeedback.comment,
            MessageFeedback.created_at,
            Message.content_text,
            Message.conversation_id,
            Message.received_at,
        )
        .join(Message, Message.id == MessageFeedback.message_id)
        .where(MessageFeedback.business_id == bid, MessageFeedback.rating == -1)
        .order_by(MessageFeedback.created_at.desc())
        .limit(5)
    )
    recent_comments = []
    for comment, ts, answer, conv_id, answered_at in rows.all():
        # Question du client = dernier message entrant juste avant la réponse.
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
        recent_comments.append(
            {
                "comment": comment,
                "question": question,
                "answer": answer,
                "created_at": ts.isoformat(),
            }
        )

    return FeedbackMetrics(
        total_rated=total,
        positive=positive,
        negative=negative,
        satisfaction_pct=satisfaction,
        coverage_rated=total,
        responses_total=responses_total,
        last_7_days={"positive": pos_7, "negative": neg_7},
        recent_comments=recent_comments,
    )
