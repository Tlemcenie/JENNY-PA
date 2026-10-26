"""Dépendances injectables FastAPI.

Centralise la création et l'injection des dépendances
(sessions DB, services, etc.) dans les routes.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.auth.api_key_crypto import verify_api_key
from jenny.api.auth.jwt_utils import decode_token
from jenny.core.logging import get_logger
from jenny.db.loading import NO_REL
from jenny.db.session import get_async_session
from jenny.domain.models.api_key import ApiKey
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.user import User

logger = get_logger(__name__)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Fournit une session DB async pour la durée d'une requête."""
    async for session in get_async_session():
        yield session


# Type alias pour injection propre dans les routes
DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(slots=True)
class CurrentPrincipal:
    """Identité authentifiée résolue depuis le JWT.

    ``business_id`` est l'espace de travail principal de l'utilisateur ; il
    sert à scoper toutes les requêtes (multi-tenant) sans jamais faire confiance
    à un identifiant fourni par le client.
    """

    # None pour une clé API
    user_id: UUID | None
    business_id: UUID | None
    email: str | None
    via_api_key: bool = False


# owner, puis admin, puis le reste
_ROLE_RANK = case(
    (BusinessMember.role == "owner", 0),
    (BusinessMember.role == "admin", 1),
    else_=2,
)


async def member_business_ids(db: AsyncSession, user_id: UUID) -> list[UUID]:
    """Salons du compte, ordre stable."""
    r = await db.execute(
        select(BusinessMember.business_id)
        .outerjoin(Business, Business.id == BusinessMember.business_id)
        .where(BusinessMember.user_id == user_id)
        .order_by(_ROLE_RANK, Business.created_at.asc(), BusinessMember.business_id.asc())
    )
    return [row[0] for row in r.all()]


def _first_uuid(values: object) -> UUID | None:
    """Premier UUID valide."""
    if not isinstance(values, list):
        return None
    for raw in values:
        try:
            return UUID(str(raw))
        except (ValueError, TypeError):
            continue
    return None


async def _principal_from_jwt(db: AsyncSession, raw: str) -> CurrentPrincipal:
    """Décode le JWT, 401 sinon."""
    try:
        payload = decode_token(raw)
        user_id = UUID(str(payload["sub"]))
    except Exception:
        raise HTTPException(401, "Token invalide") from None

    business_id = _first_uuid(payload.get("business_ids"))
    if business_id is None:
        ids = await member_business_ids(db, user_id)
        business_id = ids[0] if ids else None

    return CurrentPrincipal(
        user_id=user_id,
        business_id=business_id,
        email=payload.get("email"),
    )


async def get_current_principal(
    db: DbSession,
    authorization: str | None = Header(None, alias="Authorization"),
) -> CurrentPrincipal:
    """Décode le JWT (header ``Authorization: Bearer``) et résout le tenant.

    Le ``business_id`` provient d'abord du token ; à défaut (token sans claim,
    utilisateur historique) il est relu depuis ``business_members``. Lève 401
    si le token est absent ou invalide.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authorization Bearer requis")
    return await _principal_from_jwt(db, authorization[7:].strip())


# Type alias pour injection propre dans les routes protégées
CurrentUser = Annotated[CurrentPrincipal, Depends(get_current_principal)]


async def get_optional_principal(
    db: DbSession,
    authorization: str | None = Header(None, alias="Authorization"),
) -> CurrentPrincipal | None:
    """Comme :func:`get_current_principal`, mais renvoie ``None`` (au lieu de 401)
    quand le token est absent ou invalide.

    Pour les routes qui SCOPENT au business quand un tenant est présent, sans
    exiger l'auth au niveau de la route (l'exigence réelle vient du middleware en
    prod). Avantage : le scoping est testable même hors middleware.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        return await get_current_principal(db=db, authorization=authorization)
    except HTTPException:
        return None


OptionalUser = Annotated[CurrentPrincipal | None, Depends(get_optional_principal)]


def api_key_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """Clé API expirée ?"""
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= (now or datetime.now(UTC))


async def principal_from_api_key(db: AsyncSession, raw: str) -> CurrentPrincipal | None:
    """Clé API valide, sinon None."""
    raw = (raw or "").strip()
    if not raw.startswith("sk_"):
        return None
    # sans le salon (selectin)
    rows = await db.execute(select(ApiKey).where(ApiKey.key_prefix == raw[:16]).options(NO_REL))
    now = datetime.now(UTC)
    for key in rows.scalars().all():
        if api_key_expired(key.expires_at, now):
            continue
        # bcrypt hors de la boucle
        if await asyncio.to_thread(verify_api_key, raw, key.key_hash):
            key.last_used_at = now
            return CurrentPrincipal(
                user_id=None, business_id=key.business_id, email=None, via_api_key=True
            )
    return None


async def _tenant_from_headers(
    request: Request,
    db: AsyncSession,
    authorization: str | None,
    x_api_key: str | None,
) -> CurrentPrincipal | None:
    """JWT ou clé API, None si rien."""
    # déjà vérifiée par le middleware
    cached = getattr(request.state, "api_principal", None)
    if isinstance(cached, CurrentPrincipal):
        return cached
    if authorization and authorization.lower().startswith("bearer "):
        return await _principal_from_jwt(db, authorization[7:].strip())
    if x_api_key:
        principal = await principal_from_api_key(db, x_api_key)
        if principal is None:
            raise HTTPException(401, "Clé API invalide")
        try:
            await db.commit()
        except Exception:  # pragma: no cover - best effort
            await db.rollback()
        return principal
    return None


async def get_optional_tenant(
    request: Request,
    db: DbSession,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> CurrentPrincipal | None:
    """JWT ou clé API ; None si absent, 401 si invalide."""
    return await _tenant_from_headers(request, db, authorization, x_api_key)


async def get_tenant_principal(
    request: Request,
    db: DbSession,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> CurrentPrincipal:
    """JWT ou clé API obligatoire."""
    principal = await _tenant_from_headers(request, db, authorization, x_api_key)
    if principal is None:
        raise HTTPException(401, "Authentification requise")
    return principal


OptionalTenant = Annotated[CurrentPrincipal | None, Depends(get_optional_tenant)]
TenantUser = Annotated[CurrentPrincipal, Depends(get_tenant_principal)]


async def soft_principal(request: Request, db: AsyncSession) -> CurrentPrincipal | None:
    """Principal si valide, sinon anonyme."""
    # une seule résolution par requête
    if getattr(request.state, "soft_principal_done", False):
        return request.state.soft_principal
    try:
        principal = await _tenant_from_headers(
            request,
            db,
            request.headers.get("Authorization"),
            request.headers.get("X-API-Key"),
        )
    except HTTPException:
        principal = None
    request.state.soft_principal = principal
    request.state.soft_principal_done = True
    return principal


def resolve_business_id(
    principal: CurrentPrincipal | None,
    requested: UUID | str | None = None,
    *,
    allow_anonymous: bool = False,
) -> UUID:
    """Seul helper d'isolation entre salons.

    Authentifié : son salon, 403 si un autre est demandé ou s'il n'en a pas.
    Anonyme : 401, sauf ``allow_anonymous`` (chat public) où l'id demandé passe.
    """
    if principal is None:
        if allow_anonymous and requested is not None:
            return requested if isinstance(requested, UUID) else UUID(str(requested))
        raise HTTPException(401, "Authentification requise")
    if principal.business_id is None:
        raise HTTPException(403, "Aucun salon associé à ce compte")
    if requested is not None and str(requested) != str(principal.business_id):
        logger.warning(
            "tenant.cross_business_denied",
            principal_business=str(principal.business_id),
            requested=str(requested),
        )
        raise HTTPException(403, "Accès refusé pour ce salon")
    return principal.business_id


async def get_superuser(
    db: DbSession,
    principal: "CurrentUser",
) -> CurrentPrincipal:
    """Exige un super-administrateur plateforme (``users.is_superuser``).

    Le flag n'est pas dans le JWT : on relit l'utilisateur en base. Lève 403
    si le compte n'est pas super-admin → protège la console d'administration.
    """
    is_super = None
    if principal.user_id is not None:
        # juste le flag, pas les relations
        is_super = (
            await db.execute(select(User.is_superuser).where(User.id == principal.user_id))
        ).scalar_one_or_none()
    if not is_super:
        raise HTTPException(403, "Accès réservé aux administrateurs")
    return principal


# Injection pour les routes d'administration (super-admin uniquement).
SuperUser = Annotated[CurrentPrincipal, Depends(get_superuser)]
