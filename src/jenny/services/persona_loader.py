"""Chargement du « Cerveau de Jenny » (persona configurable d'un business).

Petit utilitaire partagé par les routes qui invoquent le moteur conversationnel :
récupère le persona (ton, règles, vocabulaire) et le nom du business pour les
injecter dans l'``EngineRequest``. Renvoie ``(None, None)`` si le business est
introuvable — le moteur retombe alors sur son comportement par défaut.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.domain.models.business import Business

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def load_business_persona(
    db: AsyncSession, business_id: UUID | str | None
) -> tuple[dict | None, str | None]:
    """Renvoie ``(persona, business_name)`` pour ce business (best-effort)."""
    if business_id is None:
        return None, None
    try:
        biz = await db.get(Business, business_id)
    except Exception:
        return None, None
    if biz is None:
        return None, None
    return biz.persona, biz.name


async def load_business_persona_fresh(
    business_id: UUID | str | None,
) -> tuple[dict | None, str | None]:
    """Idem mais ouvre sa propre session (pour les chemins sans session active,
    ex. réponses webhook)."""
    if business_id is None:
        return None, None
    from jenny.db.session import async_session_factory

    try:
        async with async_session_factory() as session:
            return await load_business_persona(session, business_id)
    except Exception:
        return None, None
