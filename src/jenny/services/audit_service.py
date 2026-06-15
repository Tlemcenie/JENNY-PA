"""Service d'écriture du journal d'audit (#16).

Petit utilitaire partagé par les routes : enregistre « qui a fait quoi » dans la
table ``audit_logs``. L'écriture rejoint la transaction du caller (simple
``session.add``) ; c'est au caller d'appeler ``commit`` — ainsi l'entrée d'audit
et la mutation métier sont atomiques (tout ou rien).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from jenny.core.logging import get_logger
from jenny.domain.models.audit_log import AuditLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def record_audit(
    session: AsyncSession,
    *,
    business_id: UUID | None,
    actor: str | None,
    action: str,
    entity_type: str,
    summary: str,
    entity_id: UUID | str | None = None,
    meta: dict | None = None,
) -> AuditLog | None:
    """Ajoute une entrée d'audit à la session courante (sans commit).

    Renvoie l'objet créé (non flushé) ou ``None`` si ``business_id`` manque.
    """
    if business_id is None:
        return None
    eid: UUID | None
    if isinstance(entity_id, str):
        try:
            eid = UUID(entity_id)
        except (ValueError, TypeError):
            eid = None
    else:
        eid = entity_id
    entry = AuditLog(
        business_id=business_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=eid,
        summary=summary,
        meta=meta,
    )
    session.add(entry)
    logger.info("audit.record", action=action, entity_type=entity_type, actor=actor)
    return entry
