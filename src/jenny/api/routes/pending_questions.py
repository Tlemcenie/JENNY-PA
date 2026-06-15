"""Questions en attente rattachées à une conversation (à traiter par l'équipe).

Quand Jenny manque d'une info pour servir un client précis (ou que le client pose
une question hors périmètre), elle la met de côté ici, liée à la conversation. Le
commerçant la voit dans le fil, y répond (et peut enregistrer la réponse dans sa
base pour que Jenny sache la fois suivante) ou la classe sans suite.

Distinct de ``KnowledgeGap`` (connaissance générale) : ici c'est contextuel à une
conversation. Tout est scopé au business du JWT.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.pending_question import PendingQuestion
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/pending-questions", tags=["Pending questions"])


class PQOut(BaseModel):
    id: str
    question: str
    origin: str
    status: str
    answer: str | None = None
    conversation_id: str | None = None
    created_at: datetime


class PQListResponse(BaseModel):
    questions: list[PQOut]
    total: int


def _to_out(q: PendingQuestion) -> PQOut:
    return PQOut(
        id=str(q.id),
        question=q.question,
        origin=q.origin,
        status=q.status,
        answer=q.answer,
        conversation_id=str(q.conversation_id) if q.conversation_id else None,
        created_at=q.created_at,
    )


@router.get("", response_model=PQListResponse)
async def list_pending_questions(
    db: DbSession,
    principal: CurrentUser,
    conversation_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[
        Literal["open", "answered", "dismissed", "all"], Query()
    ] = "open",
) -> PQListResponse:
    """Liste les questions en attente du business (les plus récentes d'abord)."""
    bid = principal.business_id
    if bid is None:
        return PQListResponse(questions=[], total=0)
    filters = [PendingQuestion.business_id == bid]
    if conversation_id is not None:
        filters.append(PendingQuestion.conversation_id == conversation_id)
    if status != "all":
        filters.append(PendingQuestion.status == status)
    rows = (
        await db.execute(
            select(PendingQuestion)
            .where(*filters)
            .order_by(PendingQuestion.created_at.desc())
        )
    ).scalars().all()
    items = [_to_out(q) for q in rows]
    return PQListResponse(questions=items, total=len(items))


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=5000)
    save_to_kb: bool = False


@router.post("/{question_id}/answer", response_model=PQOut)
async def answer_pending_question(
    question_id: UUID, body: AnswerRequest, db: DbSession, principal: CurrentUser
) -> PQOut:
    """Répond à une question en attente, et l'enregistre en base si demandé.

    Si ``save_to_kb`` est vrai, la réponse devient une connaissance du business
    (FAQ). La base vectorielle peut être indisponible (pgvector absent) : on
    conserve alors la réponse et on ignore l'enregistrement sans faire échouer.
    """
    pq = await db.get(PendingQuestion, question_id)
    if pq is None or pq.business_id != principal.business_id:
        raise HTTPException(404, "Question introuvable")

    answer = body.answer.strip()
    pq.answer = answer
    pq.status = "answered"
    pq.answered_by = principal.email or "équipe"
    pq.answered_at = datetime.now(UTC)

    if body.save_to_kb:
        try:
            kb = KnowledgeBase(business_id=pq.business_id, session=db)
            await kb.add_text(content=answer, title=pq.question[:120], category="faq")
        except Exception as exc:
            # pgvector peut être absent : on garde la réponse, on ignore le KB.
            logger.warning(
                "pending_question.kb_save_failed",
                error=str(exc),
                question_id=str(pq.id),
            )

    record_audit(
        db,
        business_id=pq.business_id,
        actor=principal.email or "équipe",
        action="pending_question.answered",
        entity_type="pending_question",
        entity_id=pq.id,
        summary=f"Réponse apportée à « {pq.question[:80]} »",
    )
    await db.commit()
    await db.refresh(pq)
    return _to_out(pq)


@router.post("/{question_id}/dismiss", response_model=PQOut)
async def dismiss_pending_question(
    question_id: UUID, db: DbSession, principal: CurrentUser
) -> PQOut:
    """Classe une question en attente sans suite (non pertinente / hors sujet)."""
    pq = await db.get(PendingQuestion, question_id)
    if pq is None or pq.business_id != principal.business_id:
        raise HTTPException(404, "Question introuvable")
    pq.status = "dismissed"
    record_audit(
        db,
        business_id=pq.business_id,
        actor=principal.email or "équipe",
        action="pending_question.dismissed",
        entity_type="pending_question",
        entity_id=pq.id,
        summary=f"Question classée sans suite : « {pq.question[:80]} »",
    )
    await db.commit()
    await db.refresh(pq)
    return _to_out(pq)
