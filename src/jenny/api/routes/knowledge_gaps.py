"""Lacunes de connaissance — boucle d'apprentissage côté propriétaire.

Le commerçant voit les vraies questions de clients auxquelles Jenny n'a pas su
répondre, y répond, et peut **enregistrer** sa réponse dans sa base de
connaissances : Jenny saura répondre la prochaine fois. Un récapitulatif liste
toutes les questions en attente pour qu'il les traite d'un coup.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.knowledge_gap import KnowledgeGap
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/knowledge-gaps", tags=["Knowledge gaps"])


class GapItem(BaseModel):
    id: str
    question: str
    channel: str | None = None
    intent: str | None = None
    status: str
    occurrences: int
    answer: str | None = None
    saved_to_kb: bool = False
    conversation_id: str | None = None
    created_at: datetime
    last_seen_at: datetime | None = None


class GapListResponse(BaseModel):
    gaps: list[GapItem]
    total: int


def _to_item(g: KnowledgeGap) -> GapItem:
    return GapItem(
        id=str(g.id),
        question=g.question,
        channel=g.channel,
        intent=g.intent,
        status=g.status,
        occurrences=g.occurrences,
        answer=g.answer,
        saved_to_kb=bool(g.saved_to_kb),
        conversation_id=str(g.conversation_id) if g.conversation_id else None,
        created_at=g.created_at,
        last_seen_at=g.last_seen_at,
    )


@router.get("", response_model=GapListResponse)
async def list_gaps(
    db: DbSession,
    principal: CurrentUser,
    status: Annotated[Literal["open", "answered", "dismissed", "all"], Query()] = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> GapListResponse:
    """Liste les lacunes du business (les plus fréquentes/récentes d'abord)."""
    bid = principal.business_id
    if bid is None:
        return GapListResponse(gaps=[], total=0)
    filters = [KnowledgeGap.business_id == bid]
    if status != "all":
        filters.append(KnowledgeGap.status == status)
    rows = (
        await db.execute(
            select(KnowledgeGap)
            .where(*filters)
            .order_by(
                KnowledgeGap.occurrences.desc(),
                func.coalesce(KnowledgeGap.last_seen_at, KnowledgeGap.created_at).desc(),
            )
            .limit(limit)
        )
    ).scalars().all()
    return GapListResponse(gaps=[_to_item(g) for g in rows], total=len(rows))


class GapStats(BaseModel):
    open: int
    answered: int
    dismissed: int
    saved_to_kb: int


@router.get("/stats", response_model=GapStats)
async def gap_stats(db: DbSession, principal: CurrentUser) -> GapStats:
    """Compteurs des lacunes par statut (pour le tableau de bord)."""
    bid = principal.business_id
    if bid is None:
        return GapStats(open=0, answered=0, dismissed=0, saved_to_kb=0)

    async def _count(*conds) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(KnowledgeGap.id)).where(
                        KnowledgeGap.business_id == bid, *conds
                    )
                )
            ).scalar_one()
            or 0
        )

    return GapStats(
        open=await _count(KnowledgeGap.status == "open"),
        answered=await _count(KnowledgeGap.status == "answered"),
        dismissed=await _count(KnowledgeGap.status == "dismissed"),
        saved_to_kb=await _count(KnowledgeGap.saved_to_kb.is_(True)),
    )


class GapRecapResponse(BaseModel):
    total_open: int
    questions: list[str]
    recap_text: str


@router.get("/recap", response_model=GapRecapResponse)
async def gap_recap(db: DbSession, principal: CurrentUser) -> GapRecapResponse:
    """Récapitulatif des questions en attente — à présenter au propriétaire.

    C'est le « résumé de toutes les questions sans réponse » : Jenny les remonte
    pour que le commerçant y réponde, puis les enregistre dans sa base.
    """
    bid = principal.business_id
    if bid is None:
        return GapRecapResponse(total_open=0, questions=[], recap_text="")
    rows = (
        await db.execute(
            select(KnowledgeGap)
            .where(KnowledgeGap.business_id == bid, KnowledgeGap.status == "open")
            .order_by(KnowledgeGap.occurrences.desc(), KnowledgeGap.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    questions = [g.question for g in rows]
    if not questions:
        recap = "Aucune question en attente — Jenny a su répondre à tout. 🎉"
    else:
        lignes = "\n".join(
            f"{i}. {g.question}"
            + (f"  (posée {g.occurrences} fois)" if g.occurrences > 1 else "")
            for i, g in enumerate(rows, 1)
        )
        recap = (
            f"Voici {len(questions)} question(s) auxquelles je n'ai pas encore pu "
            f"répondre. Si tu me donnes les réponses, je les retiens pour la suite :\n\n"
            f"{lignes}"
        )
    return GapRecapResponse(total_open=len(questions), questions=questions, recap_text=recap)


class AnswerGapRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=5000)
    save_to_kb: bool = True
    category: str = Field(default="faq", max_length=50)


class AnswerGapResponse(BaseModel):
    gap: GapItem
    saved_to_kb: bool
    knowledge_entry_id: str | None = None


@router.post("/{gap_id}/answer", response_model=AnswerGapResponse)
async def answer_gap(
    gap_id: UUID, body: AnswerGapRequest, db: DbSession, principal: CurrentUser
) -> AnswerGapResponse:
    """Répond à une lacune et, si demandé, enregistre la réponse dans la base.

    Enregistrer = la réponse devient une connaissance du business (vectorisée),
    Jenny la réutilisera automatiquement pour les prochains clients.
    """
    bid = principal.business_id
    gap = await db.get(KnowledgeGap, gap_id)
    if gap is None or gap.business_id != bid:
        raise HTTPException(404, "Lacune introuvable")

    now = datetime.now(UTC)
    gap.answer = body.answer.strip()
    gap.answered_by = principal.email or "équipe"
    gap.answered_at = now
    gap.status = "answered"

    saved = False
    entry_id: str | None = None
    if body.save_to_kb:
        try:
            kb = KnowledgeBase(business_id=bid, session=db)
            entry = await kb.add_text(
                content=body.answer.strip(),
                title=gap.question[:120],
                category=body.category or "faq",
                metadata={"source": "knowledge_gap", "gap_id": str(gap.id)},
            )
            gap.saved_to_kb = True
            gap.knowledge_entry_id = entry.id
            saved = True
            entry_id = entry.id
        except Exception as exc:
            # La base vectorielle peut être indisponible : on garde la réponse,
            # on signale juste que l'enregistrement n'a pas pu se faire.
            logger.warning("knowledge_gap.kb_save_failed", error=str(exc), gap_id=str(gap.id))

    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "équipe",
        action="knowledge_gap.answered",
        entity_type="knowledge_gap",
        entity_id=gap.id,
        summary=f"Réponse apportée à « {gap.question[:80]} »"
        + (" (enregistrée dans la base)" if saved else ""),
    )
    await db.commit()
    await db.refresh(gap)
    return AnswerGapResponse(gap=_to_item(gap), saved_to_kb=saved, knowledge_entry_id=entry_id)


@router.post("/{gap_id}/dismiss", response_model=GapItem)
async def dismiss_gap(gap_id: UUID, db: DbSession, principal: CurrentUser) -> GapItem:
    """Ignore une lacune (question non pertinente / hors sujet)."""
    gap = await db.get(KnowledgeGap, gap_id)
    if gap is None or gap.business_id != principal.business_id:
        raise HTTPException(404, "Lacune introuvable")
    gap.status = "dismissed"
    await db.commit()
    await db.refresh(gap)
    return _to_item(gap)
