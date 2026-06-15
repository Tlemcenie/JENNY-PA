"""Action : Créer un ticket support en base."""

from __future__ import annotations

import contextlib
from typing import ClassVar
from uuid import UUID

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.logging import get_logger
from jenny.db.repositories.support_ticket_repo import SupportTicketRepository
from jenny.db.session import async_session_factory

logger = get_logger(__name__)


class CreateTicketAction(BaseAction):
    """Crée un ticket de support."""

    name = "create_ticket"
    description = "Crée un ticket de support pour une réclamation ou demande d'aide"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        bid_str = params.get("business_id")
        if not bid_str:
            return ActionResult(
                success=False,
                message="Contexte business manquant pour le ticket.",
            ).to_dict()

        business_id = UUID(bid_str)
        subject = (
            params.get("description")
            or params.get("subject")
            or "Demande support"
        )
        if isinstance(subject, str) and len(subject) > 500:
            subject = subject[:497] + "..."

        customer_id = None
        if params.get("customer_id"):
            with contextlib.suppress(ValueError):
                customer_id = UUID(str(params["customer_id"]))

        ticket_id_str = ""
        ref = ""
        status = "open"
        async with async_session_factory() as session, session.begin():
            repo = SupportTicketRepository(session)
            ticket = await repo.create_ticket(
                business_id=business_id,
                customer_id=customer_id,
                subject=str(subject),
                reference=None,
                status="open",
            )
            ticket_id_str = str(ticket.id)
            ref = ticket.reference or ticket_id_str[:8]
            status = ticket.status

        logger.info("action.create_ticket.db", ticket_id=ticket_id_str)
        return ActionResult(
            success=True,
            message=f"Votre ticket {ref} a été enregistré. Nous revenons vers vous rapidement.",
            data={
                "ticket_id": ticket_id_str,
                "reference": ref,
                "status": status,
                "customer_email": params.get("email"),
            },
        ).to_dict()
