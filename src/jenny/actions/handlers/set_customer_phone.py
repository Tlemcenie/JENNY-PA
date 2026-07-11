"""Action : enregistrer le téléphone du client (après « un numéro pour te rappeler ? »).

Suite naturelle de ``set_customer_name`` en chat anonyme : une fois la fiche
créée et rattachée au rendez-vous, Jenny demande un numéro de rappel. Le message
suivant contenant un numéro est capté ici. N'écrase jamais un numéro existant.
"""

from __future__ import annotations

import re
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_PHONE_RE = re.compile(r"(?:\+?\d[\s.\-]?){8,15}")


def extract_phone(text: str) -> str | None:
    """Extrait un numéro plausible (8-15 chiffres, séparateurs tolérés)."""
    m = _PHONE_RE.search(text or "")
    if not m:
        return None
    digits = re.sub(r"[^\d+]", "", m.group())
    return digits if len(re.sub(r"\D", "", digits)) >= 8 else None


class SetCustomerPhoneAction(BaseAction):
    """Écrit le téléphone du client courant sur sa fiche."""

    name = "set_customer_phone"
    description = "Enregistre le téléphone du client (après demande)"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        business_id = params.get("business_id")
        customer_id = params.get("customer_id")
        phone = extract_phone(str(params.get("phone") or ""))
        if not business_id or not customer_id or not phone:
            return {"success": False, "phoned": False}
        try:
            return await self._save(UUID(str(customer_id)), phone)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.set_phone.error", error=str(exc))
            return {"success": False, "phoned": False}

    async def _save(self, customer_id: UUID, phone: str) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.domain.models.customer import Customer

        async with async_session_factory() as db:
            cust = await db.get(Customer, customer_id)
            if cust is None:
                return {"success": False, "phoned": False}
            # On ne remplace pas un numéro déjà connu (ex. identité WhatsApp).
            if not (cust.phone or "").strip():
                cust.phone = phone
                await db.commit()
        logger.info("action.set_phone.ok", customer_id=str(customer_id))
        return {"success": True, "phoned": True, "phone": phone}
