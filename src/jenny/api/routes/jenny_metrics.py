"""Tableau de bord « Efficacité de Jenny » — métriques agrégées réelles.

Donne au commerçant une vue de la performance de Jenny : volume traité,
lacunes de connaissance (ouvertes/résolues/apprises), et le score du dernier
banc d'essai (``var/eval/last_report.json``) s'il existe.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.knowledge_gap import KnowledgeGap
from jenny.domain.models.message import Message
from jenny.domain.models.message_feedback import MessageFeedback

logger = get_logger(__name__)

router = APIRouter(prefix="/jenny", tags=["Jenny metrics"])

_EVAL_REPORT = Path("var/eval/last_report.json")


class GapBreakdown(BaseModel):
    open: int
    answered: int
    dismissed: int
    saved_to_kb: int


class EvalSummary(BaseModel):
    score_pct: float
    scenarios: int
    turns: int
    checks_passed: int
    checks_total: int
    by_criterion: dict


class SatisfactionBreakdown(BaseModel):
    total_rated: int
    positive: int
    negative: int
    satisfaction_pct: float  # part de 👍 parmi les avis


class JennyMetrics(BaseModel):
    conversations: int
    messages: int
    customers: int
    learned_answers: int  # lacunes enregistrées dans la base = apprentissage
    gaps: GapBreakdown
    top_open_questions: list[str]
    last_eval: EvalSummary | None = None
    satisfaction: SatisfactionBreakdown = SatisfactionBreakdown(
        total_rated=0, positive=0, negative=0, satisfaction_pct=0.0
    )


@router.get("/metrics", response_model=JennyMetrics)
async def jenny_metrics(db: DbSession, principal: CurrentUser) -> JennyMetrics:
    """Métriques d'efficacité de Jenny pour le business courant."""
    bid = principal.business_id
    if bid is None:
        return JennyMetrics(
            conversations=0,
            messages=0,
            customers=0,
            learned_answers=0,
            gaps=GapBreakdown(open=0, answered=0, dismissed=0, saved_to_kb=0),
            top_open_questions=[],
            last_eval=_load_eval(),
        )

    async def _count(model, *conds) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(model.id)).where(model.business_id == bid, *conds)
                )
            ).scalar_one()
            or 0
        )

    gaps = GapBreakdown(
        open=await _count(KnowledgeGap, KnowledgeGap.status == "open"),
        answered=await _count(KnowledgeGap, KnowledgeGap.status == "answered"),
        dismissed=await _count(KnowledgeGap, KnowledgeGap.status == "dismissed"),
        saved_to_kb=await _count(KnowledgeGap, KnowledgeGap.saved_to_kb.is_(True)),
    )

    top_rows = (
        await db.execute(
            select(KnowledgeGap.question)
            .where(KnowledgeGap.business_id == bid, KnowledgeGap.status == "open")
            .order_by(KnowledgeGap.occurrences.desc(), KnowledgeGap.created_at.desc())
            .limit(5)
        )
    ).all()

    # Satisfaction : agrégée depuis les 👍/👎 laissés sur les réponses de Jenny.
    fb_pos = await _count(MessageFeedback, MessageFeedback.rating == 1)
    fb_neg = await _count(MessageFeedback, MessageFeedback.rating == -1)
    fb_total = fb_pos + fb_neg
    satisfaction = SatisfactionBreakdown(
        total_rated=fb_total,
        positive=fb_pos,
        negative=fb_neg,
        satisfaction_pct=round(100.0 * fb_pos / fb_total, 1) if fb_total else 0.0,
    )

    return JennyMetrics(
        conversations=await _count(Conversation),
        messages=await _count(Message),
        customers=await _count(Customer),
        learned_answers=gaps.saved_to_kb,
        gaps=gaps,
        top_open_questions=[r[0] for r in top_rows],
        last_eval=_load_eval(),
        satisfaction=satisfaction,
    )


def _load_eval() -> EvalSummary | None:
    """Charge le résumé du dernier rapport d'éval, si disponible."""
    try:
        if not _EVAL_REPORT.exists():
            return None
        data = json.loads(_EVAL_REPORT.read_text(encoding="utf-8"))
        s = data.get("summary") or {}
        return EvalSummary(
            score_pct=float(s.get("score_pct", 0.0)),
            scenarios=int(s.get("scenarios", 0)),
            turns=int(s.get("turns", 0)),
            checks_passed=int(s.get("checks_passed", 0)),
            checks_total=int(s.get("checks_total", 0)),
            by_criterion=s.get("by_criterion", {}),
        )
    except Exception as exc:  # pragma: no cover - lecture best-effort
        logger.warning("jenny_metrics.eval_read_failed", error=str(exc))
        return None
