"""Gestion des clés API machine-to-business (#17).

Permet au propriétaire d'un business de générer des clés ``sk_…`` (affichées une
seule fois, jamais restockées en clair), de les lister (préfixe + métadonnées) et
de les révoquer. Ces clés authentifient les appels serveur-à-serveur via l'en-tête
``X-API-Key`` (voir AuthContextMiddleware).
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jenny.api.auth.api_key_crypto import hash_api_key
from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.api_key import ApiKey
from jenny.services.audit_service import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


def _generate_key() -> tuple[str, str, str]:
    """Génère (clé_en_clair, préfixe, hash). Le préfixe (16c) sert au lookup."""
    raw = "sk_" + secrets.token_urlsafe(32)
    prefix = raw[:16]
    return raw, prefix, hash_api_key(raw)


def _scopes_list(scopes: dict | None) -> list[str]:
    if not scopes:
        return []
    items = scopes.get("scopes") if isinstance(scopes, dict) else None
    return list(items) if isinstance(items, list) else []


class ApiKeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str] = Field(default_factory=list)
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list, max_length=20)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyCreated(ApiKeyInfo):
    # La clé en clair n'est renvoyée qu'à la création, jamais ensuite.
    secret: str


@router.get("", response_model=list[ApiKeyInfo])
async def list_api_keys(db: DbSession, principal: CurrentUser) -> list[ApiKeyInfo]:
    """Liste les clés API du business (préfixe + métadonnées, sans secret)."""
    bid = principal.business_id
    if bid is None:
        return []
    rows = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.business_id == bid)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return [
        ApiKeyInfo(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=_scopes_list(k.scopes),
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            created_at=k.created_at,
        )
        for k in rows
    ]


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest, db: DbSession, principal: CurrentUser
) -> ApiKeyCreated:
    """Génère une nouvelle clé API. Le secret n'est affiché qu'ici, copiez-le."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    raw, prefix, key_hash = _generate_key()
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days)
        if body.expires_in_days
        else None
    )
    key = ApiKey(
        business_id=bid,
        name=body.name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
        scopes={"scopes": body.scopes} if body.scopes else None,
        expires_at=expires_at,
    )
    db.add(key)
    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "Agent",
        action="api_key.created",
        entity_type="api_key",
        summary=f"Clé API « {body.name.strip()} » créée",
    )
    await db.commit()
    await db.refresh(key)
    logger.info("api_key.created", business_id=str(bid), prefix=prefix)
    return ApiKeyCreated(
        id=str(key.id),
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=body.scopes,
        last_used_at=None,
        expires_at=key.expires_at,
        created_at=key.created_at,
        secret=raw,
    )


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    db: DbSession,
    principal: CurrentUser,
) -> dict:
    """Révoque (supprime) une clé API du business."""
    bid = principal.business_id
    key = await db.get(ApiKey, key_id)
    if key is None or key.business_id != bid:
        raise HTTPException(404, "Clé introuvable")
    name = key.name
    await db.delete(key)
    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "Agent",
        action="api_key.revoked",
        entity_type="api_key",
        entity_id=key_id,
        summary=f"Clé API « {name} » révoquée",
    )
    await db.commit()
    logger.info("api_key.revoked", business_id=str(bid), key_id=str(key_id))
    return {"status": "revoked", "id": str(key_id)}
