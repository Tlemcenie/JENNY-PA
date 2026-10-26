"""Catalogue de prestations — CRUD pour le propriétaire (onglet « Prestations »).

Le commerçant gère ici ses prestations (nom, catégorie, durée, prix). Jenny s'en
sert comme source de vérité pour les tarifs et la durée des rendez-vous : elle ne
peut donc rien inventer. Tout est scopé au business du JWT (multi-tenant).

Un raccourci d'onboarding (« seed-coiffeur ») installe un catalogue type de salon
de coiffure et des fiches KB tirées des vraies données du salon (horaires...).
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.prestation import Prestation
from jenny.rag import kb_sync  # noqa: F401 (suivi de la KB)
from jenny.rag.kb_coiffeur import (
    DEFAULT_COIFFEUR,
    build_entries,
    has_hours,
    load_salon,
    real_families,
    sync_real_entries,
)
from jenny.rag.knowledge_base import KnowledgeBase
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/prestations", tags=["Prestations"])


class PrestationOut(BaseModel):
    id: str
    name: str
    category: str
    duration_minutes: int
    price_cents: int
    price_eur: float
    description: str | None = None
    is_active: bool
    sort_order: int


class PrestationListResponse(BaseModel):
    prestations: list[PrestationOut]
    total: int


def _to_out(p: Prestation) -> PrestationOut:
    return PrestationOut(
        id=str(p.id),
        name=p.name,
        category=p.category,
        duration_minutes=p.duration_minutes,
        price_cents=p.price_cents,
        price_eur=p.price_eur,
        description=p.description,
        is_active=p.is_active,
        sort_order=p.sort_order,
    )


@router.get("", response_model=PrestationListResponse)
async def list_prestations(
    db: DbSession, principal: CurrentUser
) -> PrestationListResponse:
    """Liste toutes les prestations du business (actives ET inactives)."""
    bid = principal.business_id
    if bid is None:
        return PrestationListResponse(prestations=[], total=0)
    rows = (
        await db.execute(
            select(Prestation)
            .where(Prestation.business_id == bid)
            .order_by(Prestation.sort_order.asc(), Prestation.name.asc())
        )
    ).scalars().all()
    items = [_to_out(p) for p in rows]
    return PrestationListResponse(prestations=items, total=len(items))


class PrestationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="autre", max_length=40)
    duration_minutes: int = Field(default=30, ge=0, le=1440)
    price_cents: int = Field(default=0, ge=0)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    sort_order: int = 0


@router.post("", response_model=PrestationOut, status_code=201)
async def create_prestation(
    body: PrestationCreate, db: DbSession, principal: CurrentUser
) -> PrestationOut:
    """Crée une prestation pour le business courant."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    presta = Prestation(
        business_id=bid,
        name=body.name.strip(),
        category=(body.category or "autre").strip() or "autre",
        duration_minutes=body.duration_minutes,
        price_cents=body.price_cents,
        description=body.description,
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    db.add(presta)
    await db.flush()
    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "équipe",
        action="prestation.created",
        entity_type="prestation",
        entity_id=presta.id,
        summary=f"Prestation « {presta.name} » créée ({presta.price_eur:.2f} €)",
    )
    await db.commit()
    await db.refresh(presta)
    logger.info("prestation.created", business_id=str(bid), prestation_id=str(presta.id))
    return _to_out(presta)


class PrestationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=40)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    price_cents: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/{prestation_id}", response_model=PrestationOut)
async def update_prestation(
    prestation_id: UUID, body: PrestationUpdate, db: DbSession, principal: CurrentUser
) -> PrestationOut:
    """Met à jour partiellement une prestation (404 si hors du business)."""
    presta = await db.get(Prestation, prestation_id)
    if presta is None or presta.business_id != principal.business_id:
        raise HTTPException(404, "Prestation introuvable")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        presta.name = data["name"].strip()
    if "category" in data and data["category"] is not None:
        presta.category = data["category"].strip() or "autre"
    for f in ("duration_minutes", "price_cents", "is_active", "sort_order"):
        if f in data and data[f] is not None:
            setattr(presta, f, data[f])
    if "description" in data:
        presta.description = data["description"]
    record_audit(
        db,
        business_id=presta.business_id,
        actor=principal.email or "équipe",
        action="prestation.updated",
        entity_type="prestation",
        entity_id=presta.id,
        summary=f"Prestation « {presta.name} » mise à jour",
    )
    await db.commit()
    await db.refresh(presta)
    return _to_out(presta)


@router.delete("/{prestation_id}")
async def delete_prestation(
    prestation_id: UUID, db: DbSession, principal: CurrentUser
) -> dict:
    """Supprime une prestation du catalogue."""
    presta = await db.get(Prestation, prestation_id)
    if presta is None or presta.business_id != principal.business_id:
        raise HTTPException(404, "Prestation introuvable")
    name = presta.name
    record_audit(
        db,
        business_id=presta.business_id,
        actor=principal.email or "équipe",
        action="prestation.deleted",
        entity_type="prestation",
        entity_id=presta.id,
        summary=f"Prestation « {name} » supprimée",
    )
    await db.delete(presta)
    await db.commit()
    return {"status": "deleted", "id": str(prestation_id)}


# ── Onboarding coiffeur ──────────────────────────────────────────────────────

# (name, category, duration_minutes, price_cents)
_DEFAULT_COIFFEUR: list[tuple[str, str, int, int]] = DEFAULT_COIFFEUR


class SeedCoiffeurResponse(BaseModel):
    prestations: int
    knowledge: int


async def _lock_seed(db, bid: UUID) -> bool:
    """Un seed à la fois par salon."""
    if db.get_bind().dialect.name != "postgresql":
        return False
    # libéré au prochain commit
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"jenny:seed-coiffeur:{bid}"},
    )
    return True


async def _seed_knowledge(db: DbSession, bid: UUID) -> int:
    """Fiches tirées du salon réel."""
    if db.get_bind().dialect.name != "postgresql":
        # pas de pgvector (tests)
        return 0
    try:
        business, prestas, staff = await load_salon(db, bid)
        if not has_hours(business.get("business_hours")):
            # fiches horaires sautées
            logger.warning("prestation.seed_no_hours", business_id=str(bid))
        # prix : catalogue en direct
        entries = build_entries(
            business, prestas, demo=False, include_prices=False, staff=staff
        )
        kb = KnowledgeBase(business_id=bid, session=db)
        # vieilles fiches prix retirées
        stats = await sync_real_entries(
            kb, entries, families=real_families(include_prices=True)
        )
    except Exception as exc:
        # store vectoriel indispo : on ignore
        await db.rollback()
        logger.warning("prestation.seed_knowledge_failed", error=str(exc))
        return 0
    logger.info("prestation.seed_knowledge", business_id=str(bid), **stats)
    return stats["added"] + stats["updated"]


@router.post("/seed-coiffeur", response_model=SeedCoiffeurResponse)
async def seed_coiffeur(db: DbSession, principal: CurrentUser) -> SeedCoiffeurResponse:
    """Installe un catalogue type de salon de coiffure + connaissances de base.

    Idempotent : si le business possède déjà des prestations, on ne duplique rien
    (renvoie 0 prestation créée). Les fiches KB viennent des vraies données du
    salon (horaires saisis, acompte, rappels, équipe) : à appeler après la
    saisie des horaires. Relancer le seed les remet à jour, sans toucher aux
    fiches retouchées ou supprimées par le gérant. Ensuite elles suivent
    seules les changements du salon (voir jenny.rag.kb_sync).
    """
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")

    # pas de catalogue en double
    await _lock_seed(db, bid)
    existing = int(
        (
            await db.execute(
                select(func.count(Prestation.id)).where(Prestation.business_id == bid)
            )
        ).scalar_one()
        or 0
    )

    created = 0
    if existing == 0:
        for order, (name, category, duration, price_cents) in enumerate(
            _DEFAULT_COIFFEUR
        ):
            db.add(
                Prestation(
                    business_id=bid,
                    name=name,
                    category=category,
                    duration_minutes=duration,
                    price_cents=price_cents,
                    is_active=True,
                    sort_order=order,
                )
            )
            created += 1
        await db.flush()
        record_audit(
            db,
            business_id=bid,
            actor=principal.email or "équipe",
            action="prestation.seeded",
            entity_type="business",
            entity_id=bid,
            summary=f"Catalogue coiffeur initialisé ({created} prestations)",
        )
        await db.commit()

    knowledge = await _seed_knowledge(db, bid)

    logger.info(
        "prestation.seeded",
        business_id=str(bid),
        prestations=created,
        knowledge=knowledge,
    )
    return SeedCoiffeurResponse(prestations=created, knowledge=knowledge)
