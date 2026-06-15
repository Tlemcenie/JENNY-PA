"""Action : inscrire le client en liste d'attente (salon complet).

Déclenchée quand, après un « aucun créneau libre », le client accepte d'être
prévenu dès qu'une place se libère. On enregistre une ``WaitlistEntry`` réelle
rattachée au business (et à la conversation/au client si connus), puis on renvoie
le rang dans la file pour une confirmation fondée.

Robuste par construction : toute incertitude renvoie un résultat « non abouti »
exploité en conversation, sans planter.
"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)


class JoinWaitlistAction(BaseAction):
    """Inscrit le client courant en liste d'attente du salon."""

    name = "join_waitlist"
    description = "Inscrit le client en liste d'attente quand le salon est complet"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        business_id = params.get("business_id")
        if not business_id:
            return {"success": False, "message": "Contexte business absent."}
        try:
            return await self._join(UUID(str(business_id)), params)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.join_waitlist.error", error=str(exc))
            return {
                "success": False,
                "message": "Inscription en liste d'attente non finalisée (à confirmer avec l'équipe).",
            }

    async def _join(self, bid: UUID, params: dict) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.services.waitlist_service import add_to_waitlist, waitlist_position

        service = params.get("service")
        # La fenêtre souhaitée reprend le jour demandé lors de la tentative de RDV.
        desired = (params.get("date") or params.get("desired_window") or "").strip()[:200] or None
        customer_id = params.get("customer_id")
        conversation_id = params.get("conversation_id")
        # Contact éventuel déjà capté en conversation (email/téléphone) pour rappeler.
        contact = params.get("email") or params.get("phone")
        name = params.get("name") or params.get("customer_name")

        async with async_session_factory() as db:
            entry = await add_to_waitlist(
                db,
                business_id=bid,
                service=service,
                desired_window=desired,
                customer_id=UUID(str(customer_id)) if customer_id else None,
                conversation_id=UUID(str(conversation_id)) if conversation_id else None,
                customer_name=name,
                customer_contact=contact,
            )
            position = await waitlist_position(db, entry)
            await db.commit()

        logger.info("action.join_waitlist.ok", entry_id=str(entry.id), business_id=str(bid))
        return {
            "success": True,
            "waitlisted": True,
            "service": service or entry.service,
            "position": position,
            "message": "Inscription en liste d'attente confirmée.",
        }
