"""Action : Paiement Stripe / PayPal (API réelles si configurées)."""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID, uuid4

import httpx

from jenny.actions.base import ActionResult, BaseAction
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.payment_repo import PaymentRepository
from jenny.db.session import async_session_factory

logger = get_logger(__name__)


class ProcessPaymentAction(BaseAction):
    """Traite un paiement."""

    name = "process_payment"
    description = "Initie ou vérifie un paiement pour une commande"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        order_number = params.get("order_number")
        amount = params.get("amount")
        bid_str = params.get("business_id")
        settings = get_settings()

        payment_id = f"PAY-{uuid4().hex[:8].upper()}"
        logger.info(
            "action.process_payment",
            payment_id=payment_id,
            order_number=order_number,
            amount=amount,
        )

        if not bid_str:
            return ActionResult(
                success=False,
                message="Contexte business manquant pour le paiement.",
            ).to_dict()

        business_id = UUID(bid_str)

        if settings.stripe_secret_key and amount:
            try:
                cents = int(float(str(amount).replace(",", ".")) * 100)
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        "https://api.stripe.com/v1/payment_intents",
                        data={
                            "amount": str(cents),
                            "currency": "eur",
                            "metadata[order_number]": order_number or "",
                            "metadata[business_id]": str(business_id),
                        },
                        auth=(settings.stripe_secret_key, ""),
                        timeout=30.0,
                    )
                    r.raise_for_status()
                    data = r.json()
                ext_id = data.get("id", payment_id)
                async with async_session_factory() as session, session.begin():
                    repo = PaymentRepository(session)
                    await repo.upsert_status(
                        business_id=business_id,
                        provider="stripe",
                        external_id=ext_id,
                        status=data.get("status", "requires_payment_method"),
                        amount_minor=cents,
                        order_reference=str(order_number) if order_number else None,
                    )
                return ActionResult(
                    success=True,
                    message="Paiement initié (Stripe). Suivez les instructions sécurisées.",
                    data={
                        "payment_id": ext_id,
                        "client_secret": data.get("client_secret"),
                        "status": data.get("status"),
                        "provider": "stripe",
                    },
                ).to_dict()
            except Exception as e:
                logger.error("action.process_payment.stripe_error", error=str(e))
                return ActionResult(
                    success=False,
                    message="Impossible d'initier le paiement Stripe pour le moment.",
                ).to_dict()

        if settings.paypal_client_id and settings.paypal_client_secret and amount:
            try:
                token = await self._paypal_token()
                amt_val = float(str(amount).replace(",", "."))
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{settings.paypal_base_url}/v2/checkout/orders",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "intent": "CAPTURE",
                            "purchase_units": [
                                {
                                    "amount": {
                                        "currency_code": "EUR",
                                        "value": f"{amt_val:.2f}",
                                    },
                                    "reference_id": order_number or payment_id,
                                }
                            ],
                        },
                        timeout=30.0,
                    )
                    r.raise_for_status()
                    pdata = r.json()
                ext_id = pdata.get("id", payment_id)
                approve = next(
                    (lk["href"] for lk in pdata.get("links", []) if lk.get("rel") == "approve"),
                    None,
                )
                async with async_session_factory() as session, session.begin():
                    repo = PaymentRepository(session)
                    await repo.upsert_status(
                        business_id=business_id,
                        provider="paypal",
                        external_id=ext_id,
                        status=pdata.get("status", "CREATED"),
                        amount_minor=int(amt_val * 100),
                        order_reference=str(order_number) if order_number else None,
                    )
                return ActionResult(
                    success=True,
                    message="Commande PayPal créée. Ouvrez le lien pour payer.",
                    data={
                        "payment_id": ext_id,
                        "approve_url": approve,
                        "provider": "paypal",
                    },
                ).to_dict()
            except Exception as e:
                logger.error("action.process_payment.paypal_error", error=str(e))
                return ActionResult(
                    success=False,
                    message="Impossible d'initier le paiement PayPal pour le moment.",
                ).to_dict()

        return ActionResult(
            success=True,
            message=(
                "Pour effectuer un paiement, configurez STRIPE_SECRET_KEY ou PayPal "
                "et indiquez un montant."
            ),
            data={
                "payment_id": payment_id,
                "status": "pending_config",
            },
        ).to_dict()

    async def _paypal_token(self) -> str:
        s = get_settings()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{s.paypal_base_url}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(s.paypal_client_id, s.paypal_client_secret),
                timeout=30.0,
            )
            r.raise_for_status()
            return r.json()["access_token"]
