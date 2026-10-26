"""Relances : segments, campagnes, trous d'agenda.

Tout est scopé au salon du jeton (principal.business_id) : jamais
un business_id envoyé par le client.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession  # noqa: TC001
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.campaign import Campaign
from jenny.domain.models.customer import Customer
from jenny.services import campaigns as svc
from jenny.services import gap_filler
from jenny.services.availability import business_tz
from jenny.services.offer_cap import set_opt_out

logger = get_logger(__name__)

router = APIRouter(prefix="/campaigns", tags=["Relances"])


def _bid(principal) -> UUID:
    """Salon du jeton, sinon 403."""
    if principal.business_id is None:
        raise HTTPException(status_code=403, detail="Aucun salon rattaché à ce compte.")
    return principal.business_id


async def _business(db, bid: UUID) -> Business:
    """Salon courant, sinon 404."""
    biz = await db.get(Business, bid)
    if biz is None:
        raise HTTPException(status_code=404, detail="Salon introuvable.")
    return biz


# ── schémas ──


class SegmentOut(BaseModel):
    key: str
    label: str
    description: str
    suggestion: str
    count: int
    reachable: int
    eligible: int


class SampleCustomer(BaseModel):
    id: UUID
    name: str
    visits: int
    last_visit_at: datetime | None = None
    no_shows: int = 0
    reachable: bool
    eligible: bool
    # a répondu STOP
    opt_out: bool = False


class SegmentPreview(SegmentOut):
    sample: list[SampleCustomer]


class RenderIn(BaseModel):
    message: str = Field(..., max_length=svc.MAX_MESSAGE_LEN)
    name: str | None = Field(default=None, max_length=60)


class RenderOut(BaseModel):
    text: str
    length: int
    sms_parts: int
    unicode: bool


class CampaignIn(BaseModel):
    segment: str = Field(..., max_length=40)
    message: str = Field(..., min_length=svc.MIN_MESSAGE_LEN, max_length=svc.MAX_MESSAGE_LEN)


class CampaignOut(BaseModel):
    id: UUID
    segment: str
    segment_label: str
    message: str
    status: str
    created_at: datetime
    created_by: str | None = None
    target_count: int
    sent_count: int
    skipped_count: int
    returned_count: int
    revenue_eur: float
    window_ends_at: datetime
    window_open: bool


class CampaignSummary(BaseModel):
    campaigns: int
    sent: int
    returned: int
    revenue_eur: float
    return_rate_pct: float


class CampaignHistory(BaseModel):
    summary: CampaignSummary
    campaigns: list[CampaignOut]


class GapOut(BaseModel):
    start: datetime
    label: str


class PlannedOut(BaseModel):
    name: str
    source: str
    service: str | None = None
    slot_start: datetime
    label: str
    duration_minutes: int


class GapsOut(BaseModel):
    gaps: list[GapOut]
    candidates: int
    planned: list[PlannedOut]
    sent_7d: int
    failed_7d: int
    filled_7d: int
    in_send_hours: bool


class GapRunOut(BaseModel):
    sent: int
    failed: int
    planned: int
    skipped: str | None = None


class OptOutIn(BaseModel):
    opt_out: bool


class OptOutOut(BaseModel):
    customer_id: UUID
    opt_out: bool
    opt_out_at: datetime | None = None


class OptOutItem(BaseModel):
    id: UUID
    name: str
    opt_out_at: datetime


class OptOutList(BaseModel):
    total: int
    customers: list[OptOutItem]


# ── segments ──


def _seg_out(seg: svc.Segment, counts: dict[str, int]) -> dict:
    return {
        "key": seg.key,
        "label": seg.label,
        "description": seg.description,
        "suggestion": seg.suggestion,
        **counts,
    }


@router.get("/segments", response_model=list[SegmentOut])
async def list_segments(db: DbSession, principal: CurrentUser) -> list[SegmentOut]:
    """Les 4 segments avec leurs effectifs."""
    bid = _bid(principal)
    now = datetime.now(UTC)
    out = []
    for seg in svc.SEGMENTS.values():
        counts = await svc.segment_counts(db, bid, seg.key, now)
        out.append(SegmentOut(**_seg_out(seg, counts)))
    return out


@router.get("/segments/{key}", response_model=SegmentPreview)
async def preview_segment(
    key: str,
    db: DbSession,
    principal: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> SegmentPreview:
    """Aperçu : effectif + échantillon."""
    bid = _bid(principal)
    seg = svc.SEGMENTS.get(key)
    if seg is None:
        raise HTTPException(status_code=404, detail="Segment inconnu.")
    now = datetime.now(UTC)
    counts = await svc.segment_counts(db, bid, key, now)
    members = await svc.segment_members(db, bid, key, now, limit=limit)
    convs = await svc.direct_conversations(db, bid, [m.customer.id for m in members])
    sample = []
    for m in members:
        reach = svc.is_reachable(m.customer, convs)
        sample.append(
            SampleCustomer(
                id=m.customer.id,
                name=m.customer.full_name or "Client",
                visits=m.visits,
                last_visit_at=m.last_visit,
                no_shows=m.no_shows,
                reachable=reach,
                eligible=reach and svc.can_offer(m.customer, now),
                opt_out=m.customer.marketing_opt_out_at is not None,
            )
        )
    return SegmentPreview(**_seg_out(seg, counts), sample=sample)


@router.post("/render", response_model=RenderOut)
async def render(body: RenderIn, db: DbSession, principal: CurrentUser) -> RenderOut:
    """Texte final tel que reçu par le client."""
    biz = await _business(db, _bid(principal))
    text = svc.render_message(
        body.message, name=svc.first_name(body.name or "Marie"), salon=biz.name or "Votre salon"
    )
    return RenderOut(
        text=text, length=len(text), sms_parts=svc.sms_parts(text), unicode=not svc.is_gsm(text)
    )


# ── campagnes ──


@router.post("", response_model=CampaignOut, status_code=202)
async def send_campaign(
    body: CampaignIn,
    background: BackgroundTasks,
    db: DbSession,
    principal: CurrentUser,
) -> CampaignOut:
    """Crée la campagne, l'envoi part en fond."""
    bid = _bid(principal)
    await _business(db, bid)
    try:
        camp = await svc.create_campaign(
            db,
            business_id=bid,
            segment=body.segment,
            message=body.message,
            created_by=principal.email,
        )
    except svc.CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # visible pour la tâche de fond
    await db.commit()
    background.add_task(svc.deliver_campaign_job, camp.id)
    seg = svc.SEGMENTS[camp.segment]
    created = camp.created_at if camp.created_at.tzinfo else camp.created_at.replace(tzinfo=UTC)
    return CampaignOut(
        id=camp.id,
        segment=camp.segment,
        segment_label=seg.label,
        message=camp.message,
        status=camp.status,
        created_at=created,
        created_by=camp.created_by,
        target_count=camp.target_count,
        sent_count=0,
        skipped_count=0,
        returned_count=0,
        revenue_eur=0.0,
        window_ends_at=created + timedelta(days=svc.ATTRIBUTION_DAYS),
        window_open=True,
    )


@router.get("", response_model=CampaignHistory)
async def history(
    db: DbSession,
    principal: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> CampaignHistory:
    """Historique + clientes revenues."""
    bid = _bid(principal)
    items = await svc.campaign_history(db, bid, limit=limit)
    sent = sum(i["sent_count"] for i in items)
    returned = sum(i["returned_count"] for i in items)
    total = int(
        (
            await db.execute(select(func.count(Campaign.id)).where(Campaign.business_id == bid))
        ).scalar_one()
    )
    return CampaignHistory(
        summary=CampaignSummary(
            campaigns=total,
            sent=sent,
            returned=returned,
            revenue_eur=round(sum(i["revenue_eur"] for i in items), 2),
            return_rate_pct=round(100 * returned / sent, 1) if sent else 0.0,
        ),
        campaigns=[CampaignOut(**i) for i in items],
    )


# ── trous d'agenda ──


@router.get("/gaps", response_model=GapsOut)
async def gaps_preview(db: DbSession, principal: CurrentUser) -> GapsOut:
    """Créneaux libres + qui serait prévenu (sans envoyer)."""
    biz = await _business(db, _bid(principal))
    now = datetime.now(UTC)
    tz = business_tz(biz)
    rep = await gap_filler.fill_gaps_for_business(db, biz, now=now, dry_run=True)
    stats = await gap_filler.offer_stats(db, biz.id, now=now)
    return GapsOut(
        gaps=[GapOut(start=g, label=gap_filler.when_label(g, tz, now)) for g in rep.gaps],
        candidates=rep.candidates,
        planned=[
            PlannedOut(
                name=p.candidate.name or "Client",
                source=p.candidate.source,
                service=p.candidate.service,
                slot_start=p.slot_start,
                label=gap_filler.when_label(p.slot_start, tz, now),
                duration_minutes=p.candidate.duration,
            )
            for p in rep.planned
        ],
        sent_7d=stats["sent"],
        failed_7d=stats["failed"],
        filled_7d=stats["filled"],
        in_send_hours=gap_filler.in_send_hours(biz, now),
    )


@router.post("/gaps/run", response_model=GapRunOut)
async def gaps_run(db: DbSession, principal: CurrentUser) -> GapRunOut:
    """Le gérant lance le remplissage tout de suite."""
    biz = await _business(db, _bid(principal))
    # jamais 2 passes ensemble
    async with gap_filler.business_lock(biz.id):
        rep = await gap_filler.fill_gaps_for_business(db, biz, reason="manuel")
    return GapRunOut(
        sent=rep.sent, failed=rep.failed, planned=len(rep.planned), skipped=rep.skipped
    )


# ── désinscription ──


async def _own_customer(db, bid: UUID, customer_id: UUID) -> Customer:
    """Client du salon, sinon 404."""
    cust = await db.get(Customer, customer_id)
    if cust is None or cust.business_id != bid:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    return cust


@router.get("/opt-outs", response_model=OptOutList)
async def list_opt_outs(
    db: DbSession,
    principal: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> OptOutList:
    """Clientes qui refusent les offres."""
    bid = _bid(principal)
    where = (
        Customer.business_id == bid,
        Customer.anonymized_at.is_(None),
        Customer.marketing_opt_out_at.is_not(None),
    )
    total = int((await db.execute(select(func.count(Customer.id)).where(*where))).scalar_one() or 0)
    rows = (
        await db.execute(
            select(Customer.id, Customer.full_name, Customer.marketing_opt_out_at)
            .where(*where)
            .order_by(Customer.marketing_opt_out_at.desc())
            .limit(limit)
        )
    ).all()
    items = [
        OptOutItem(id=cid, name=name or "Client", opt_out_at=_utc(at)) for cid, name, at in rows
    ]
    return OptOutList(total=total, customers=items)


def _utc(dt: datetime) -> datetime:
    """Naïve -> UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.get("/opt-out/{customer_id}", response_model=OptOutOut)
async def get_opt_out(customer_id: UUID, db: DbSession, principal: CurrentUser) -> OptOutOut:
    """Refus des offres d'un client."""
    cust = await _own_customer(db, _bid(principal), customer_id)
    at = cust.marketing_opt_out_at
    return OptOutOut(
        customer_id=cust.id, opt_out=at is not None, opt_out_at=_utc(at) if at else None
    )


@router.put("/opt-out/{customer_id}", response_model=OptOutOut)
async def opt_out(
    customer_id: UUID, body: OptOutIn, db: DbSession, principal: CurrentUser
) -> OptOutOut:
    """Coche ou décoche le refus des offres."""
    cust = await _own_customer(db, _bid(principal), customer_id)
    # déjà coché : date gardée
    if body.opt_out != (cust.marketing_opt_out_at is not None):
        set_opt_out(cust, body.opt_out)
        logger.info("campaigns.opt_out_set", customer_id=str(cust.id), opt_out=body.opt_out)
    await db.flush()
    at = cust.marketing_opt_out_at
    return OptOutOut(customer_id=cust.id, opt_out=body.opt_out, opt_out_at=_utc(at) if at else None)
