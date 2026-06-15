"""Catalogue de prestations — CRUD pour le propriétaire (onglet « Prestations »).

Le commerçant gère ici ses prestations (nom, catégorie, durée, prix). Jenny s'en
sert comme source de vérité pour les tarifs et la durée des rendez-vous : elle ne
peut donc rien inventer. Tout est scopé au business du JWT (multi-tenant).

Un raccourci d'onboarding (« seed-coiffeur ») installe un catalogue type de salon
de coiffure et quelques connaissances de base si le business démarre à vide.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.prestation import Prestation
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
_DEFAULT_COIFFEUR: list[tuple[str, str, int, int]] = [
    ("Coupe femme", "coupe", 45, 3900),
    ("Coupe homme", "coupe", 30, 2500),
    ("Brushing", "coiffage", 30, 2500),
    ("Coloration", "couleur", 90, 5500),
    ("Balayage", "couleur", 120, 8000),
    ("Soin profond", "soin", 30, 2000),
    ("Barbe", "barbe", 20, 1500),
]

# (title, category, content) — connaissances de base pour Jenny.
_DEFAULT_KNOWLEDGE: list[tuple[str, str, str]] = [
    (
        "Horaires d'ouverture",
        "horaires",
        "Le salon est ouvert du mardi au samedi, de 9h à 19h. "
        "Fermé le dimanche et le lundi.",
    ),
    (
        "Politique d'annulation",
        "politique",
        "Pour annuler ou déplacer un rendez-vous, merci de prévenir au moins "
        "24 heures à l'avance. Toute annulation tardive ou non-présentation "
        "pourra être facturée.",
    ),
]


class SeedCoiffeurResponse(BaseModel):
    prestations: int
    knowledge: int


@router.post("/seed-coiffeur", response_model=SeedCoiffeurResponse)
async def seed_coiffeur(db: DbSession, principal: CurrentUser) -> SeedCoiffeurResponse:
    """Installe un catalogue type de salon de coiffure + connaissances de base.

    Idempotent : si le business possède déjà des prestations, on ne duplique rien
    (renvoie 0 prestation créée). Les connaissances passent par la base
    vectorielle, qui peut être indisponible (pgvector absent) : on ignore alors
    proprement sans faire échouer la requête.
    """
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")

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

    knowledge = 0
    for title, category, content in _DEFAULT_KNOWLEDGE:
        try:
            kb = KnowledgeBase(business_id=bid, session=db)
            await kb.add_text(content=content, title=title, category=category)
            knowledge += 1
        except Exception as exc:
            # pgvector peut être absent (ex. SQLite en test) : on ignore proprement.
            logger.warning(
                "prestation.seed_knowledge_failed", error=str(exc), title=title
            )

    logger.info(
        "prestation.seeded",
        business_id=str(bid),
        prestations=created,
        knowledge=knowledge,
    )
    return SeedCoiffeurResponse(prestations=created, knowledge=knowledge)
