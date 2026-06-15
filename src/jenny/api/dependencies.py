"""Dépendances injectables FastAPI.

Centralise la création et l'injection des dépendances
(sessions DB, services, etc.) dans les routes.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.auth.jwt_utils import decode_token
from jenny.db.session import get_async_session
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.user import User


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

    user_id: UUID
    business_id: UUID | None
    email: str | None


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
    raw = authorization[7:].strip()
    try:
        payload = decode_token(raw)
        user_id = UUID(payload["sub"])
    except Exception:
        raise HTTPException(401, "Token invalide") from None

    business_id: UUID | None = None
    for bid in payload.get("business_ids") or []:
        try:
            business_id = UUID(bid)
            break
        except (ValueError, TypeError):
            continue

    if business_id is None:
        r = await db.execute(
            select(BusinessMember.business_id)
            .where(BusinessMember.user_id == user_id)
            .limit(1)
        )
        business_id = r.scalar_one_or_none()

    return CurrentPrincipal(
        user_id=user_id,
        business_id=business_id,
        email=payload.get("email"),
    )


# Type alias pour injection propre dans les routes protégées
CurrentUser = Annotated[CurrentPrincipal, Depends(get_current_principal)]


async def get_superuser(
    db: DbSession,
    principal: "CurrentUser",
) -> CurrentPrincipal:
    """Exige un super-administrateur plateforme (``users.is_superuser``).

    Le flag n'est pas dans le JWT : on relit l'utilisateur en base. Lève 403
    si le compte n'est pas super-admin → protège la console d'administration.
    """
    user = await db.get(User, principal.user_id)
    if user is None or not user.is_superuser:
        raise HTTPException(403, "Accès réservé aux administrateurs")
    return principal


# Injection pour les routes d'administration (super-admin uniquement).
SuperUser = Annotated[CurrentPrincipal, Depends(get_superuser)]
