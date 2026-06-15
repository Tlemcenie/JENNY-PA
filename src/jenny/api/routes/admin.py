"""Console d'administration plateforme (super-admin).

Réservé aux comptes ``users.is_superuser`` (dépendance ``SuperUser``). Permet de
superviser toute la plateforme : entreprises, comptes, volumétrie — et quelques
actions de gestion (activer/désactiver une entreprise, promouvoir un admin).
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from jenny.api.dependencies import DbSession, SuperUser
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.user import User
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


class AdminOverview(BaseModel):
    businesses: int
    users: int
    conversations: int
    messages: int
    customers: int


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(db: DbSession, _: SuperUser) -> AdminOverview:
    """Compteurs plateforme (toutes entreprises confondues)."""

    async def _count(model) -> int:
        return int((await db.execute(select(func.count(model.id)))).scalar_one() or 0)

    return AdminOverview(
        businesses=await _count(Business),
        users=await _count(User),
        conversations=await _count(Conversation),
        messages=await _count(Message),
        customers=await _count(Customer),
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


@router.get("/businesses", response_model=list[AdminBusiness])
async def admin_businesses(db: DbSession, _: SuperUser) -> list[AdminBusiness]:
    """Liste toutes les entreprises avec leurs compteurs."""
    rows = (await db.execute(select(Business).order_by(Business.created_at.desc()))).scalars().all()
    out: list[AdminBusiness] = []
    for b in rows:
        members = int(
            (
                await db.execute(
                    select(func.count(BusinessMember.id)).where(
                        BusinessMember.business_id == b.id
                    )
                )
            ).scalar_one()
            or 0
        )
        convs = int(
            (
                await db.execute(
                    select(func.count(Conversation.id)).where(
                        Conversation.business_id == b.id
                    )
                )
            ).scalar_one()
            or 0
        )
        out.append(
            AdminBusiness(
                id=str(b.id),
                name=b.name,
                slug=b.slug,
                email=b.email,
                is_active=bool(b.is_active),
                members=members,
                conversations=convs,
                created_at=b.created_at,
            )
        )
    return out


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
    rows = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    out: list[AdminUser] = []
    for u in rows:
        n = int(
            (
                await db.execute(
                    select(func.count(BusinessMember.id)).where(
                        BusinessMember.user_id == u.id
                    )
                )
            ).scalar_one()
            or 0
        )
        out.append(
            AdminUser(
                id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                email_verified=bool(u.email_verified),
                is_superuser=bool(u.is_superuser),
                businesses=n,
                created_at=u.created_at,
            )
        )
    return out


class BusinessActiveUpdate(BaseModel):
    is_active: bool


@router.patch("/businesses/{business_id}/active", response_model=AdminBusiness)
async def admin_set_business_active(
    business_id: UUID, body: BusinessActiveUpdate, db: DbSession, principal: SuperUser
) -> AdminBusiness:
    """Active ou suspend une entreprise."""
    b = await db.get(Business, business_id)
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
    await db.refresh(b)
    logger.info(
        "admin.business_active", business_id=business_id, active=body.is_active,
        by=principal.email,
    )
    members = int(
        (
            await db.execute(
                select(func.count(BusinessMember.id)).where(
                    BusinessMember.business_id == b.id
                )
            )
        ).scalar_one()
        or 0
    )
    convs = int(
        (
            await db.execute(
                select(func.count(Conversation.id)).where(Conversation.business_id == b.id)
            )
        ).scalar_one()
        or 0
    )
    return AdminBusiness(
        id=str(b.id),
        name=b.name,
        slug=b.slug,
        email=b.email,
        is_active=bool(b.is_active),
        members=members,
        conversations=convs,
        created_at=b.created_at,
    )


class SuperuserUpdate(BaseModel):
    is_superuser: bool


@router.patch("/users/{user_id}/superuser", response_model=AdminUser)
async def admin_set_superuser(
    user_id: UUID, body: SuperuserUpdate, db: DbSession, principal: SuperUser
) -> AdminUser:
    """Promeut ou révoque un administrateur plateforme."""
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if str(u.id) == str(principal.user_id) and not body.is_superuser:
        raise HTTPException(400, "Vous ne pouvez pas retirer vos propres droits admin")
    u.is_superuser = body.is_superuser
    await db.commit()
    await db.refresh(u)
    logger.info("admin.set_superuser", user_id=user_id, value=body.is_superuser, by=principal.email)
    n = int(
        (
            await db.execute(
                select(func.count(BusinessMember.id)).where(BusinessMember.user_id == u.id)
            )
        ).scalar_one()
        or 0
    )
    return AdminUser(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        email_verified=bool(u.email_verified),
        is_superuser=bool(u.is_superuser),
        businesses=n,
        created_at=u.created_at,
    )
