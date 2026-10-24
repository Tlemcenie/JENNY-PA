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

# Politesses éventuelles autour du nom (« c'est Marie », « c'est pour Marie »).
# Ordre : les préfixes longs AVANT « c'est » seul (sinon « pour » reste collé).
_STRIP_RE = re.compile(
    r"^\s*(?:c['’]est\s+pour|c['’]est\s+au\s+nom\s+de|moi\s+c['’]est|"  # noqa: RUF001
    r"je\s+m['’]appelle|mon\s+nom\s+(?:c['’]est|est)|au\s+nom\s+de|"  # noqa: RUF001
    r"je\s+suis|c['’]est|pour)\s+",  # noqa: RUF001
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
        appointment_id = params.get("appointment_id")
        raw = params.get("name") or ""
        clean = _clean_name(raw)
        if not business_id or len(clean) < 2 or not (customer_id or appointment_id):
            return {"success": False, "named": False}
        try:
            if customer_id:
                return await self._save(UUID(str(customer_id)), clean)
            # Chat anonyme : le RDV vient d'être pris SANS client — on crée la fiche
            # avec le nom donné et on la rattache au rendez-vous de la conversation.
            return await self._create_and_attach(
                UUID(str(business_id)), UUID(str(appointment_id)), clean
            )
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
            ask_phone = not (cust.phone or "").strip()
        logger.info("action.set_name.ok", customer_id=str(customer_id))
        return {
            "success": True,
            "named": True,
            "name": clean,
            "ask_phone": ask_phone,
            "customer_id": str(customer_id),
        }

    async def _create_and_attach(self, bid: UUID, appointment_id: UUID, clean: str) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.domain.models.appointment import Appointment
        from jenny.domain.models.customer import Customer

        async with async_session_factory() as db:
            appt = await db.get(Appointment, appointment_id)
            if appt is None or appt.business_id != bid:
                return {"success": False, "named": False}
            if appt.customer_id is not None:
                # Un client existe déjà (course rare) : on complète son nom si vide.
                return await self._save(appt.customer_id, clean)
            cust = Customer(business_id=bid, full_name=clean)
            db.add(cust)
            await db.flush()
            appt.customer_id = cust.id
            await db.commit()
            cid = str(cust.id)
        logger.info("action.set_name.created", customer_id=cid, appointment_id=str(appointment_id))
        return {"success": True, "named": True, "name": clean, "ask_phone": True, "customer_id": cid}
