"""Webhooks Stripe / PayPal pour mise à jour des statuts de paiement."""

from __future__ import annotations

from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from jenny.api.dependencies import DbSession  # noqa: TC001 — résolu au runtime par FastAPI
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.db.repositories.payment_repo import PaymentRepository
from jenny.domain.models.payment_record import PaymentRecord

logger = get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["Payment webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: DbSession) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "Stripe webhook non configuré")
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(400, "Missing stripe-signature")
    try:
        stripe.api_key = settings.stripe_secret_key
        event = stripe.Webhook.construct_event(
            payload,
            sig,
            settings.stripe_webhook_secret,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except stripe.SignatureVerificationError as e:
        raise HTTPException(400, "Invalid signature") from e

    et = event["type"]
    obj = event["data"]["object"]
    if et == "payment_intent.succeeded":
        ext_id = obj.get("id")
        meta = obj.get("metadata") or {}
        bid = meta.get("business_id")
        if ext_id and bid:
            repo = PaymentRepository(db)
            await repo.upsert_status(
                business_id=__import__("uuid").UUID(bid),
                provider="stripe",
                external_id=ext_id,
                status="succeeded",
                amount_minor=obj.get("amount"),
                order_reference=meta.get("order_number"),
            )
            await db.commit()
    elif et == "checkout.session.completed":
        # Acompte anti-no-show réglé → on confirme le RDV associé.
        meta = obj.get("metadata") or {}
        if meta.get("kind") == "deposit":
            repo = PaymentRepository(db)
            payment = await repo.get_by_external("stripe", obj.get("id"))
            if payment is not None:
                from jenny.services.deposit_service import mark_deposit_paid_by_payment

                await mark_deposit_paid_by_payment(db, payment=payment)
                await db.commit()
                logger.info("payment_webhook.deposit_paid", session=obj.get("id"))
    logger.info("payment_webhook.stripe", type=et)
    return {"status": "ok"}


@router.post("/paypal")
async def paypal_webhook(request: Request, db: DbSession) -> dict[str, str]:
    """Webhook PayPal (simplifié : met à jour si resource existe)."""
    body: dict[str, Any] = await request.json()
    event_type = body.get("event_type", "")
    resource = body.get("resource") or {}
    order_id = resource.get("id")
    if not order_id:
        return {"status": "ignored"}

    stmt = select(PaymentRecord).where(
        PaymentRecord.provider == "paypal",
        PaymentRecord.external_id == order_id,
    )
    r = await db.execute(stmt)
    row = r.scalar_one_or_none()
    if row:
        row.status = resource.get("status", event_type)
        await db.commit()
    logger.info("payment_webhook.paypal", event=event_type)
    return {"status": "ok"}
