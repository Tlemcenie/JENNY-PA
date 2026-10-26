"""Console d'administration plateforme (super-admin).

Réservé aux comptes ``users.is_superuser`` (dépendance ``SuperUser``). Permet de
superviser toute la plateforme : entreprises, comptes, volumétrie — et quelques
actions de gestion (activer/désactiver une entreprise, promouvoir un admin).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import raiseload

from jenny.api.dependencies import DbSession, SuperUser
from jenny.core.logging import get_logger
from jenny.domain.models.audit_log import AuditLog
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.user import User
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_USER_COLS = ["email", "full_name", "email_verified", "is_superuser", "created_at"]


def _count(model, *where):
    """COUNT en sous-requête."""
    return select(func.count(model.id)).where(*where).scalar_subquery()


class AdminOverview(BaseModel):
    businesses: int
    users: int
    conversations: int
    messages: int
    customers: int


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(db: DbSession, _: SuperUser) -> AdminOverview:
    """Compteurs plateforme (toutes entreprises confondues)."""
    # un seul aller-retour
    row = (
        await db.execute(
            select(
                _count(Business),
                _count(User),
                _count(Conversation),
                _count(Message),
                _count(Customer),
            )
        )
    ).one()
    businesses, users, conversations, messages, customers = (int(n or 0) for n in row)
    return AdminOverview(
        businesses=businesses,
        users=users,
        conversations=conversations,
        messages=messages,
        customers=customers,
    )


class AdminBusiness(BaseModel):
    id: str
    name: str
    slug: str
    email: str | None = None
    is_active: bool
    members: int
    conversations: int
    created_at: datetime


def _business_rows():
    """Entreprises + compteurs groupés."""
    members = (
        select(BusinessMember.business_id.label("bid"), func.count(BusinessMember.id).label("n"))
        .group_by(BusinessMember.business_id)
        .subquery()
    )
    convs = (
        select(Conversation.business_id.label("bid"), func.count(Conversation.id).label("n"))
        .group_by(Conversation.business_id)
        .subquery()
    )
    return (
        select(
            Business.id,
            Business.name,
            Business.slug,
            Business.email,
            Business.is_active,
            Business.created_at,
            func.coalesce(members.c.n, 0).label("members"),
            func.coalesce(convs.c.n, 0).label("conversations"),
        )
        .outerjoin(members, members.c.bid == Business.id)
        .outerjoin(convs, convs.c.bid == Business.id)
    )


def _to_admin_business(r) -> AdminBusiness:
    """Ligne SQL vers schéma."""
    return AdminBusiness(
        id=str(r.id),
        name=r.name,
        slug=r.slug,
        email=r.email,
        is_active=bool(r.is_active),
        members=int(r.members or 0),
        conversations=int(r.conversations or 0),
        created_at=r.created_at,
    )


@router.get("/businesses", response_model=list[AdminBusiness])
async def admin_businesses(db: DbSession, _: SuperUser) -> list[AdminBusiness]:
    """Liste toutes les entreprises avec leurs compteurs."""
    rows = (await db.execute(_business_rows().order_by(Business.created_at.desc()))).all()
    return [_to_admin_business(r) for r in rows]


class AdminUser(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    email_verified: bool
    is_superuser: bool
    businesses: int
    created_at: datetime


@router.get("/users", response_model=list[AdminUser])
async def admin_users(db: DbSession, _: SuperUser) -> list[AdminUser]:
    """Liste tous les comptes utilisateurs de la plateforme."""
    per_user = (
        select(BusinessMember.user_id.label("uid"), func.count(BusinessMember.id).label("n"))
        .group_by(BusinessMember.user_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                User.id,
                User.email,
                User.full_name,
                User.email_verified,
                User.is_superuser,
                User.created_at,
                func.coalesce(per_user.c.n, 0).label("businesses"),
            )
            .outerjoin(per_user, per_user.c.uid == User.id)
            .order_by(User.created_at.desc())
        )
    ).all()
    return [
        AdminUser(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            email_verified=bool(u.email_verified),
            is_superuser=bool(u.is_superuser),
            businesses=int(u.businesses or 0),
            created_at=u.created_at,
        )
        for u in rows
    ]


class BusinessActiveUpdate(BaseModel):
    is_active: bool


@router.patch("/businesses/{business_id}/active", response_model=AdminBusiness)
async def admin_set_business_active(
    business_id: UUID, body: BusinessActiveUpdate, db: DbSession, principal: SuperUser
) -> AdminBusiness:
    """Active ou suspend une entreprise."""
    b = await db.get(Business, business_id, options=[raiseload("*")])
    if b is None:
        raise HTTPException(404, "Entreprise introuvable")
    b.is_active = body.is_active
    record_audit(
        db,
        business_id=b.id,
        actor=principal.email or "admin",
        action="admin.business_active",
        entity_type="business",
        entity_id=b.id,
        summary=f"Entreprise {'réactivée' if body.is_active else 'suspendue'} par un admin",
        meta={"is_active": body.is_active},
    )
    await db.commit()
    logger.info(
        "admin.business_active", business_id=business_id, active=body.is_active,
        by=principal.email,
    )
    # relu avec ses compteurs
    row = (await db.execute(_business_rows().where(Business.id == business_id))).one()
    return _to_admin_business(row)


class SuperuserUpdate(BaseModel):
    is_superuser: bool


@router.patch("/users/{user_id}/superuser", response_model=AdminUser)
async def admin_set_superuser(
    user_id: UUID, body: SuperuserUpdate, db: DbSession, principal: SuperUser
) -> AdminUser:
    """Promeut ou révoque un administrateur plateforme."""
    u = await db.get(User, user_id, options=[raiseload("*")])
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if str(u.id) == str(principal.user_id) and not body.is_superuser:
        raise HTTPException(400, "Vous ne pouvez pas retirer vos propres droits admin")
    u.is_superuser = body.is_superuser
    await db.commit()
    # colonnes seules, pas les liens
    await db.refresh(u, attribute_names=_USER_COLS)
    logger.info("admin.set_superuser", user_id=user_id, value=body.is_superuser, by=principal.email)
    n = await db.scalar(
        select(func.count(BusinessMember.id)).where(BusinessMember.user_id == u.id)
    )
    return AdminUser(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        email_verified=bool(u.email_verified),
        is_superuser=bool(u.is_superuser),
        businesses=int(n or 0),
        created_at=u.created_at,
    )


# ── Journal d'audit GLOBAL (toutes entreprises) ──
# Même forme de réponse que ``routes/audit.py`` (AuditItem / AuditListResponse),
# mais SANS filtre business_id : la console plateforme voit « qui a fait quoi »
# sur l'ensemble des entreprises. Données 100% réelles (table audit_logs).


class AdminAuditItem(BaseModel):
    id: str
    actor: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    summary: str
    meta: dict | None = None
    created_at: datetime
    # Champs additionnels propres à la vue globale : on rattache chaque ligne
    # à son entreprise pour que l'admin sache de qui il s'agit.
    business_id: str
    business_name: str | None = None


class AdminAuditListResponse(BaseModel):
    items: list[AdminAuditItem]
    total: int


@router.get("/audit", response_model=AdminAuditListResponse)
async def admin_audit(
    db: DbSession,
    _: SuperUser,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminAuditListResponse:
    """Historique d'audit GLOBAL de la plateforme (le plus récent d'abord).

    Lecture seule de toute la table ``audit_logs``, toutes entreprises
    confondues. ``q`` filtre (insensible à la casse) sur action / summary /
    actor.
    """
    filters = []
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                AuditLog.action.ilike(like),
                AuditLog.summary.ilike(like),
                AuditLog.actor.ilike(like),
            )
        )

    total = (
        await db.execute(select(func.count(AuditLog.id)).where(*filters))
    ).scalar_one()
    # nom du salon par jointure
    rows = (
        await db.execute(
            select(AuditLog, Business.name)
            .outerjoin(Business, Business.id == AuditLog.business_id)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(raiseload("*"))
        )
    ).all()

    return AdminAuditListResponse(
        items=[
            AdminAuditItem(
                id=str(a.id),
                actor=a.actor,
                action=a.action,
                entity_type=a.entity_type,
                entity_id=str(a.entity_id) if a.entity_id else None,
                summary=a.summary,
                meta=a.meta,
                created_at=a.created_at,
                business_id=str(a.business_id),
                business_name=business_name,
            )
            for a, business_name in rows
        ],
        total=int(total or 0),
    )
