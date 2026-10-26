"""Chargement ORM sans cascade selectin.

Les modèles déclarent beaucoup de relations ``lazy="selectin"`` qui se
chaînent (RDV -> client -> conversations -> messages -> pièces jointes).
Ici, une option explicite pour ne charger que la ligne demandée.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import raiseload

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

# aucune relation chargée
NO_REL = raiseload("*")


async def get_light[T](db: AsyncSession, model: type[T], ident: UUID) -> T | None:
    """db.get sans les relations."""
    return await db.get(model, ident, options=[NO_REL])
