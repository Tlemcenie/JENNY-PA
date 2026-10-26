"""Webhooks Stripe / PayPal pour mise à jour des statuts de paiement.

Jamais de traitement non signé : Stripe via ``stripe-signature``, PayPal via
l'API ``verify-webhook-signature`` (``JENNY_PAYPAL_WEBHOOK_ID``). Non configuré
→ 503.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
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


def _uuid_or_none(raw: object) -> UUID | None:
    """UUID ou None."""
    try:
        return UUID(str(raw)) if raw else None
    except (ValueError, TypeError):
        return None


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
        bid = _uuid_or_none(meta.get("business_id"))
        if ext_id and bid:
            repo = PaymentRepository(db)
            await repo.upsert_status(
                business_id=bid,
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
            bid = _uuid_or_none(meta.get("business_id"))
            if payment is not None and bid is not None and payment.business_id != bid:
                # salon incohérent : on ignore
                logger.warning("payment_webhook.stripe_business_mismatch", session=obj.get("id"))
                payment = None
            if payment is not None:
                from jenny.services.deposit_service import mark_deposit_paid_by_payment

                await mark_deposit_paid_by_payment(db, payment=payment)
                await db.commit()
                logger.info("payment_webhook.deposit_paid", session=obj.get("id"))
    logger.info("payment_webhook.stripe", type=et)
    return {"status": "ok"}


# en-têtes de signature PayPal
_PAYPAL_HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}

# statuts PayPal acceptés
_PAYPAL_STATUSES = {
    "CREATED",
    "SAVED",
    "APPROVED",
    "VOIDED",
    "COMPLETED",
    "PAYER_ACTION_REQUIRED",
    "PENDING",
    "DECLINED",
    "DENIED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
    "FAILED",
}


async def _paypal_access_token(client: httpx.AsyncClient) -> str:
    """Token OAuth PayPal."""
    s = get_settings()
    r = await client.post(
        f"{s.paypal_base_url}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(s.paypal_client_id, s.paypal_client_secret),
        timeout=15.0,
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


async def verify_paypal_signature(headers: dict[str, str], raw_body: bytes) -> bool:
    """Signature vérifiée par PayPal."""
    s = get_settings()
    fields = {key: headers.get(name, "") for key, name in _PAYPAL_HEADERS.items()}
    if not all(fields.values()):
        return False
    fields["webhook_id"] = s.paypal_webhook_id
    # corps brut, sans re-sérialiser
    head = json.dumps(fields)[:-1]
    payload = f'{head}, "webhook_event": {raw_body.decode("utf-8")}}}'
    try:
        async with httpx.AsyncClient() as client:
            token = await _paypal_access_token(client)
            r = await client.post(
                f"{s.paypal_base_url}/v1/notifications/verify-webhook-signature",
                content=payload.encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json().get("verification_status") == "SUCCESS"
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.error("payment_webhook.paypal_verify_error", error=str(exc))
        # PayPal réessaiera
        raise HTTPException(502, "Vérification PayPal indisponible") from exc


def _paypal_target(resource: dict[str, Any]) -> tuple[str | None, UUID | None]:
    """Id de commande + salon éventuel."""
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    # capture : on remonte à la commande
    order_id = related.get("order_id") or resource.get("id")
    custom = resource.get("custom_id")
    if not custom:
        for unit in resource.get("purchase_units") or []:
            if isinstance(unit, dict) and unit.get("custom_id"):
                custom = unit["custom_id"]
                break
    return (str(order_id) if order_id else None), _uuid_or_none(custom)


@router.post("/paypal")
async def paypal_webhook(request: Request, db: DbSession) -> dict[str, str]:
    """Webhook PayPal signé : met à jour le paiement du bon salon."""
    settings = get_settings()
    if not (
        settings.paypal_webhook_id and settings.paypal_client_id and settings.paypal_client_secret
    ):
        raise HTTPException(503, "PayPal webhook non configuré")

    raw = await request.body()
    try:
        body: dict[str, Any] = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(400, "Invalid JSON") from e
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid JSON")

    headers = {k.lower(): v for k, v in request.headers.items()}
    if not await verify_paypal_signature(headers, raw):
        logger.warning("payment_webhook.paypal_bad_signature")
        raise HTTPException(400, "Invalid signature")

    event_type = str(body.get("event_type", ""))
    resource = body.get("resource") or {}
    if not isinstance(resource, dict):
        return {"status": "ignored"}
    order_id, business_id = _paypal_target(resource)
    if not order_id:
        return {"status": "ignored"}

    stmt = select(PaymentRecord).where(
        PaymentRecord.provider == "paypal",
        PaymentRecord.external_id == order_id,
    )
    if business_id is not None:
        # filtre salon
        stmt = stmt.where(PaymentRecord.business_id == business_id)
    rows = list((await db.execute(stmt)).scalars().all())
    if len(rows) != 1:
        # absent ou ambigu : rien
        logger.warning("payment_webhook.paypal_unmatched", order_id=order_id, matches=len(rows))
        return {"status": "ignored"}

    status = str(resource.get("status") or "").upper()
    if status not in _PAYPAL_STATUSES:
        logger.info("payment_webhook.paypal_unknown_status", event_type=event_type)
        return {"status": "ignored"}
    rows[0].status = status
    await db.commit()
    logger.info(
        "payment_webhook.paypal", event_type=event_type, business_id=str(rows[0].business_id)
    )
    return {"status": "ok"}
