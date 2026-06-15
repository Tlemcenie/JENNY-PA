"""Configuration du business (espace de travail de l'utilisateur).

Permet au propriétaire de consulter et modifier les informations de son
business : nom, email, téléphone, description, fuseau horaire. Le business
ciblé est toujours celui du JWT (multi-tenant), jamais un id fourni par le
client.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/business", tags=["Business"])


class BusinessResponse(BaseModel):
    """Représentation publique d'un business."""

    id: str
    name: str
    slug: str
    email: str | None = None
    phone: str | None = None
    description: str | None = None
    timezone: str
    is_active: bool
    business_hours: dict | None = None
    auto_reply_message: str | None = None
    sla_minutes: int = 30
    sla_rules: dict | None = None
    persona: dict | None = None
    # Acompte anti-no-show.
    deposit_enabled: bool = False
    deposit_percent: int = 30
    deposit_min_cents: int = 1000
    # Rappels configurables + fidélité.
    reminder_lead_minutes: int = 60
    day_reminder_lead_hours: int = 24
    loyalty_threshold: int = 10
    created_at: datetime


class BusinessUpdateRequest(BaseModel):
    """Mise à jour partielle du business (seuls les champs fournis sont appliqués)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=5000)
    timezone: str | None = Field(None, min_length=1, max_length=64)
    business_hours: dict | None = None
    auto_reply_message: str | None = Field(None, max_length=2000)
    sla_minutes: int | None = Field(None, ge=1, le=10080)
    # SLA fins par priorité/canal : {"priority": {"high": 10}, "channel": {...}}.
    sla_rules: dict | None = None
    # Cerveau de Jenny : ton, curseurs, règles d'or, vocabulaire.
    persona: dict | None = None
    # Acompte anti-no-show : activer + pourcentage du prix + forfait sans prix.
    deposit_enabled: bool | None = None
    deposit_percent: int | None = Field(None, ge=0, le=100)
    deposit_min_cents: int | None = Field(None, ge=0, le=1_000_000)
    # Rappels configurables + seuil de fidélité.
    reminder_lead_minutes: int | None = Field(None, ge=5, le=1440)
    day_reminder_lead_hours: int | None = Field(None, ge=1, le=168)
    loyalty_threshold: int | None = Field(None, ge=0, le=100)


def _to_response(business: Business) -> BusinessResponse:
    return BusinessResponse(
        id=str(business.id),
        name=business.name,
        slug=business.slug,
        email=business.email,
        phone=business.phone,
        description=business.description,
        timezone=business.timezone,
        is_active=business.is_active,
        business_hours=business.business_hours,
        auto_reply_message=business.auto_reply_message,
        sla_minutes=business.sla_minutes,
        sla_rules=business.sla_rules,
        persona=business.persona,
        deposit_enabled=business.deposit_enabled,
        deposit_percent=business.deposit_percent,
        deposit_min_cents=business.deposit_min_cents,
        reminder_lead_minutes=business.reminder_lead_minutes,
        day_reminder_lead_hours=business.day_reminder_lead_hours,
        loyalty_threshold=business.loyalty_threshold,
        created_at=business.created_at,
    )


async def _load_business(db, principal: CurrentUser) -> Business:
    if principal.business_id is None:
        raise HTTPException(404, "Aucun business associé à ce compte")
    r = await db.execute(select(Business).where(Business.id == principal.business_id))
    business = r.scalar_one_or_none()
    if business is None:
        raise HTTPException(404, "Business introuvable")
    return business


@router.get("/me", response_model=BusinessResponse)
async def get_my_business(db: DbSession, principal: CurrentUser) -> BusinessResponse:
    """Configuration du business de l'utilisateur courant."""
    business = await _load_business(db, principal)
    return _to_response(business)


@router.patch("/me", response_model=BusinessResponse)
async def update_my_business(
    body: BusinessUpdateRequest,
    db: DbSession,
    principal: CurrentUser,
) -> BusinessResponse:
    """Met à jour la configuration du business (nom, email, téléphone, etc.)."""
    business = await _load_business(db, principal)

    updates = body.model_dump(exclude_unset=True)
    if updates.get("name"):
        business.name = updates["name"].strip()
    if "email" in updates:
        business.email = updates["email"]
    if "phone" in updates:
        business.phone = updates["phone"] or None
    if "description" in updates:
        business.description = updates["description"] or None
    if updates.get("timezone"):
        business.timezone = updates["timezone"]
    if "business_hours" in updates:
        business.business_hours = updates["business_hours"] or None
    if "auto_reply_message" in updates:
        business.auto_reply_message = updates["auto_reply_message"] or None
    if updates.get("sla_minutes"):
        business.sla_minutes = updates["sla_minutes"]
    if "sla_rules" in updates:
        business.sla_rules = updates["sla_rules"] or None
    if "persona" in updates:
        business.persona = updates["persona"] or None
    if "deposit_enabled" in updates and updates["deposit_enabled"] is not None:
        business.deposit_enabled = bool(updates["deposit_enabled"])
    if updates.get("deposit_percent") is not None:
        business.deposit_percent = int(updates["deposit_percent"])
    if updates.get("deposit_min_cents") is not None:
        business.deposit_min_cents = int(updates["deposit_min_cents"])
    if updates.get("reminder_lead_minutes") is not None:
        business.reminder_lead_minutes = int(updates["reminder_lead_minutes"])
    if updates.get("day_reminder_lead_hours") is not None:
        business.day_reminder_lead_hours = int(updates["day_reminder_lead_hours"])
    if updates.get("loyalty_threshold") is not None:
        business.loyalty_threshold = int(updates["loyalty_threshold"])

    await db.commit()
    await db.refresh(business)
    logger.info("business.updated", business_id=str(business.id))
    return _to_response(business)


class MemberItem(BaseModel):
    user_id: str
    email: str
    full_name: str | None = None
    role: str


@router.get("/members", response_model=list[MemberItem])
async def list_members(
    db: DbSession,
    principal: CurrentUser,
) -> list[MemberItem]:
    """Liste les membres de l'équipe du business (pour l'assignation)."""
    bid = principal.business_id
    if bid is None:
        return []
    rows = (
        await db.execute(
            select(User.id, User.email, User.full_name, BusinessMember.role)
            .join(BusinessMember, BusinessMember.user_id == User.id)
            .where(BusinessMember.business_id == bid)
            .order_by(User.full_name.asc())
        )
    ).all()
    return [
        MemberItem(user_id=str(uid), email=email, full_name=fn, role=role)
        for uid, email, fn, role in rows
    ]


class MemberCreate(BaseModel):
    email: EmailStr
    full_name: str | None = Field(None, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field("member", pattern="^(owner|admin|member|agent)$")


@router.post("/members", response_model=MemberItem, status_code=201)
async def add_member(
    body: MemberCreate,
    db: DbSession,
    principal: CurrentUser,
) -> MemberItem:
    """Ajoute un membre à l'équipe (crée son compte s'il n'existe pas encore).

    Le propriétaire fournit un mot de passe initial : le membre peut se connecter
    immédiatement. Si l'email correspond déjà à un compte, on le rattache juste
    à l'équipe.
    """
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")

    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None:
        from jenny.api.auth.password_utils import hash_password

        user = User(
            email=body.email,
            full_name=body.full_name,
            password_hash=hash_password(body.password),
            email_verified=True,
        )
        db.add(user)
        await db.flush()

    existing = (
        await db.execute(
            select(BusinessMember).where(
                BusinessMember.user_id == user.id, BusinessMember.business_id == bid
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(BusinessMember(user_id=user.id, business_id=bid, role=body.role))
    await db.commit()

    logger.info("business.member_added", business_id=str(bid), email=body.email)
    return MemberItem(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=body.role,
    )
