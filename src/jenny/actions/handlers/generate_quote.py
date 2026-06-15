"""Action : Génération de devis.

Crée un devis personnalisé et l'envoie au client.
En production, intégration avec un système de facturation.
"""

from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)


class GenerateQuoteAction(BaseAction):
    """Génère un devis personnalisé."""

    name = "generate_quote"
    description = "Crée un devis personnalisé pour le client"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        """Génère le devis.

        Args:
            params: {"product": "iPhone 15", "email": "client@mail.com", "name": "Dupont"}

        Returns:
            Confirmation de création du devis.
        """
        quote_id = f"DEV-{uuid4().hex[:8].upper()}"
        product = params.get("product", "Prestation sur mesure")
        email = params.get("email")
        name = params.get("name")

        logger.info(
            "action.generate_quote",
            quote_id=quote_id,
            product=product,
            email=email,
        )

        # Simulation — en prod, création dans le système de facturation
        message = f"Devis {quote_id} créé avec succès pour : {product}."
        if email:
            message += f" Il sera envoyé à {email} sous 24h."
        if name:
            message += f" Au nom de {name}."

        return ActionResult(
            success=True,
            message=message,
            data={
                "quote_id": quote_id,
                "product": product,
                "email": email,
                "customer_name": name,
                "status": "created",
                "validity_days": 30,
            },
        ).to_dict()
