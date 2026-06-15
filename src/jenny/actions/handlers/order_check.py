"""Action : Vérifier le statut d'une commande (base interne)."""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.logging import get_logger
from jenny.db.repositories.order_repo import OrderRepository
from jenny.db.session import async_session_factory

logger = get_logger(__name__)


class CheckOrderAction(BaseAction):
    """Vérifie le statut d'une commande."""

    name = "check_order"
    description = "Vérifie le statut d'une commande à partir de son numéro"
    required_params: ClassVar[tuple[str, ...]] = ("order_number",)

    async def execute(self, params: dict) -> dict:
        order_number = params.get("order_number", "")
        missing = self.validate_params(params)
        if missing:
            return ActionResult(
                success=False,
                message=f"Paramètres manquants : {missing}",
            ).to_dict()

        bid_str = params.get("business_id")
        if not bid_str:
            return ActionResult(
                success=False,
                message="Contexte business manquant pour la commande.",
            ).to_dict()

        business_id = UUID(bid_str)
        async with async_session_factory() as session:
            repo = OrderRepository(session)
            order = await repo.get_by_reference(business_id, order_number)

        if order is None:
            return ActionResult(
                success=True,
                message=(
                    f"Aucune commande « {order_number} » trouvée dans notre système. "
                    "Vérifiez le numéro ou contactez-nous."
                ),
                data={"order_number": order_number, "status": "not_found"},
            ).to_dict()

        total = order.total_amount_minor
        total_str = f"{total / 100:.2f} {order.currency}" if total is not None else "N/A"

        logger.info("action.check_order.db", order_id=str(order.id), reference=order.reference)
        return ActionResult(
            success=True,
            message=f"Commande {order.reference or order_number} : statut « {order.status} ».",
            data={
                "order_number": order.reference or order_number,
                "status": order.status,
                "currency": order.currency,
                "total": total_str,
            },
        ).to_dict()
