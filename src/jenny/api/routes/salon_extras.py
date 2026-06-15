"""Fonctions salon complémentaires : fermetures, avis, fidélité.

- Fermetures exceptionnelles (#89) : congés/fériés pris en compte par la dispo.
- Avis clients (#92) : note + commentaire, alimentent la note moyenne du salon.
- Fidélité (#93) : points d'un client + état de la récompense.

Tout est scopé au business du JWT.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession  # noqa: TC001
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.business_closure import BusinessClosure
from jenny.domain.models.review import Review
from jenny.services.loyalty_service import compute_loyalty

logger = get_logger(__name__)

router = APIRouter(prefix="/salon", tags=["Salon extras"])


# ── Fermetures exceptionnelles (#89) ──────────────────────────────────────────


class ClosureItem(BaseModel):
    id: str
    start_date: date
    end_date: date
    reason: str | None = None


class ClosureCreate(BaseModel):
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=200)


@router.get("/closures", response_model=list[ClosureItem])
async def list_closures(db: DbSession, principal: CurrentUser) -> list[ClosureItem]:
    bid = principal.business_id
    if bid is None:
        return []
    rows = (
        await db.execute(
            select(BusinessClosure)
            .where(BusinessClosure.business_id == bid)
            .order_by(BusinessClosure.start_date.asc())
        )
    ).scalars().all()
    return [
        ClosureItem(id=str(c.id), start_date=c.start_date, end_date=c.end_date, reason=c.reason)
        for c in rows
    ]


@router.post("/closures", response_model=ClosureItem, status_code=201)
async def create_closure(
    body: ClosureCreate, db: DbSession, principal: CurrentUser
) -> ClosureItem:
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    end = body.end_date or body.start_date
    if end < body.start_date:
        raise HTTPException(400, "La fin doit être postérieure ou égale au début")
    closure = BusinessClosure(
        business_id=bid, start_date=body.start_date, end_date=end, reason=body.reason
    )
    db.add(closure)
    await db.commit()
    await db.refresh(closure)
    logger.info("salon.closure_created", business_id=str(bid))
    return ClosureItem(
        id=str(closure.id), start_date=closure.start_date,
        end_date=closure.end_date, reason=closure.reason,
    )


@router.delete("/closures/{closure_id}")
async def delete_closure(
    closure_id: UUID, db: DbSession, principal: CurrentUser
) -> dict:
    closure = await db.get(BusinessClosure, closure_id)
    if closure is None or closure.business_id != principal.business_id:
        raise HTTPException(404, "Fermeture introuvable")
    await db.delete(closure)
    await db.commit()
    return {"status": "deleted", "id": str(closure_id)}


# ── Avis clients (#92) ────────────────────────────────────────────────────────


class ReviewItem(BaseModel):
    id: str
    rating: int
    comment: str | None = None
    customer_id: str | None = None
    appointment_id: str | None = None
    created_at: str


class ReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    customer_id: UUID | None = None
    appointment_id: UUID | None = None


@router.get("/reviews", response_model=list[ReviewItem])
async def list_reviews(db: DbSession, principal: CurrentUser) -> list[ReviewItem]:
    bid = principal.business_id
    if bid is None:
        return []
    rows = (
        await db.execute(
            select(Review)
            .where(Review.business_id == bid)
            .order_by(Review.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        ReviewItem(
            id=str(r.id), rating=r.rating, comment=r.comment,
            customer_id=str(r.customer_id) if r.customer_id else None,
            appointment_id=str(r.appointment_id) if r.appointment_id else None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/reviews", response_model=ReviewItem, status_code=201)
async def create_review(
    body: ReviewCreate, db: DbSession, principal: CurrentUser
) -> ReviewItem:
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    review = Review(
        business_id=bid, rating=body.rating, comment=body.comment,
        customer_id=body.customer_id, appointment_id=body.appointment_id,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    logger.info("salon.review_created", business_id=str(bid), rating=body.rating)
    return ReviewItem(
        id=str(review.id), rating=review.rating, comment=review.comment,
        customer_id=str(review.customer_id) if review.customer_id else None,
        appointment_id=str(review.appointment_id) if review.appointment_id else None,
        created_at=review.created_at.isoformat() if review.created_at else "",
    )


# ── Fidélité (#93) ────────────────────────────────────────────────────────────


class LoyaltyResponse(BaseModel):
    points: int
    threshold: int
    reward_ready: bool
    remaining: int | None = None


@router.get("/loyalty/{customer_id}", response_model=LoyaltyResponse)
async def customer_loyalty(
    customer_id: UUID, db: DbSession, principal: CurrentUser
) -> LoyaltyResponse:
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    business = await db.get(Business, bid)
    data = await compute_loyalty(db, business, customer_id)
    return LoyaltyResponse(**data)
