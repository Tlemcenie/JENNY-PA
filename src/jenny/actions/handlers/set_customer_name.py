"""Action : enregistrer le nom du client (après « c'est à quel nom ? »).

Quand un RDV est pris pour un client sans nom (typique d'un premier contact
WhatsApp sans nom de profil), Jenny demande son nom ; le message suivant est
capté ici et écrit sur la fiche client. N'écrase jamais un nom déjà renseigné.
"""

from __future__ import annotations

import re
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

# Politesses éventuelles autour du nom (« c'est Marie », « moi c'est Marie »).
_STRIP_RE = re.compile(
    r"^\s*(?:c['’]est|moi\s+c['’]est|je\s+m['’]appelle|au\s+nom\s+de|"  # noqa: RUF001
    r"c['’]est\s+pour)\s+",  # noqa: RUF001
    re.I,
)


def _clean_name(raw: str) -> str:
    """Nettoie le nom : retire la politesse, met une majuscule à chaque mot."""
    t = _STRIP_RE.sub("", (raw or "").strip()).strip(" .!,")
    t = re.sub(r"\s+", " ", t)
    return " ".join(w.capitalize() for w in t.split()[:3])


class SetCustomerNameAction(BaseAction):
    """Écrit le nom du client courant sur sa fiche."""

    name = "set_customer_name"
    description = "Enregistre le nom du client (après demande)"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        business_id = params.get("business_id")
        customer_id = params.get("customer_id")
        raw = params.get("name") or ""
        clean = _clean_name(raw)
        if not business_id or not customer_id or len(clean) < 2:
            return {"success": False, "named": False}
        try:
            return await self._save(UUID(str(customer_id)), clean)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.set_name.error", error=str(exc))
            return {"success": False, "named": False}

    async def _save(self, customer_id: UUID, clean: str) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.domain.models.customer import Customer

        async with async_session_factory() as db:
            cust = await db.get(Customer, customer_id)
            if cust is None:
                return {"success": False, "named": False}
            # On ne remplace pas un nom déjà connu (ex. nom de profil WhatsApp).
            if not (cust.full_name or "").strip():
                cust.full_name = clean
                await db.commit()
        logger.info("action.set_name.ok", customer_id=str(customer_id))
        return {"success": True, "named": True, "name": clean}
