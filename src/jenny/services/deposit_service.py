"""Service acompte — anti-no-show.

Demander un acompte à la réservation décourage les lapins (no-shows). Le salon
active la politique (``deposit_enabled`` + ``deposit_percent``) ; à chaque RDV
créé par Jenny, on calcule l'acompte et on ouvre un règlement :

- **Stripe réel** si une clé est configurée → Checkout Session (lien de paiement) ;
- **Mode manuel** sinon (par défaut) → on enregistre l'acompte « pending » en base
  (``PaymentRecord``), le salon l'encaisse sur place / par son propre lien et le
  marque payé. Le SUIVI est 100 % réel ; seul l'encaissement carte requiert Stripe.

Tout passe par la session DB de l'appelant (pas de commit ici).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.domain.models.payment_record import PaymentRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from jenny.domain.models.appointment import Appointment
    from jenny.domain.models.business import Business

logger = get_logger(__name__)


def compute_deposit_cents(
    business: Business | None, price_eur: float | None, *, force: bool = False
) -> int | None:
    """Montant d'acompte (centimes) selon la politique du salon, ou None si désactivé.

    Pourcentage du prix de la prestation quand il est connu ; sinon, acompte
    forfaitaire (``deposit_min_cents``). Renvoie None si la politique est désactivée
    (sauf ``force=True``, ex. client récidiviste du lapin) ou montant nul.
    """
    if not business:
        return None
    if not force and not getattr(business, "deposit_enabled", False):
        return None
    percent = max(0, min(100, int(getattr(business, "deposit_percent", 30) or 0)))
    if force and percent == 0:
        percent = 30
    if price_eur:
        cents = round(float(price_eur) * 100 * percent / 100)
        return cents or None
    fixed = int(getattr(business, "deposit_min_cents", 0) or 0)
    return fixed or None


async def create_deposit_for_appointment(
    db: AsyncSession,
    *,
    business: Business,
    appointment: Appointment,
    price_eur: float | None,
    service_name: str | None = None,
    force: bool = False,
) -> dict | None:
    """Ouvre un acompte pour un RDV (Stripe réel si clé, sinon mode manuel).

    Met à jour ``appointment.deposit_*`` et crée un ``PaymentRecord`` « pending ».
    Renvoie un dict exploitable par Jenny ({montant, lien, mode}), ou None si la
    politique d'acompte est désactivée / montant nul. ``force=True`` impose l'acompte
    même si la politique est désactivée (ex. client récidiviste du lapin).
    """
    amount_cents = compute_deposit_cents(business, price_eur, force=force)
    if not amount_cents:
        return None

    settings = get_settings()
    provider = "manual"
    external_id = f"dep_{appointment.id}"
    checkout_url: str | None = None

    if settings.stripe_secret_key:
        url, ext = _create_stripe_checkout(
            settings.stripe_secret_key,
            amount_cents=amount_cents,
            business=business,
            appointment=appointment,
            service_name=service_name,
        )
        if url and ext:
            provider, external_id, checkout_url = "stripe", ext, url

    record = PaymentRecord(
        business_id=business.id,
        provider=provider,
        external_id=external_id,
        amount_minor=amount_cents,
        currency="EUR",
        status="pending",
        order_reference=f"acompte:{appointment.id}",
        metadata_={
            "kind": "deposit",
            "appointment_id": str(appointment.id),
            "checkout_url": checkout_url,
        },
    )
    db.add(record)
    await db.flush()

    appointment.deposit_cents = amount_cents
    appointment.deposit_status = "pending"
    appointment.deposit_payment_id = record.id

    logger.info(
        "deposit.created",
        appointment_id=str(appointment.id),
        amount_cents=amount_cents,
        mode=provider,
    )
    return {
        "amount_cents": amount_cents,
        "amount_eur": round(amount_cents / 100, 2),
        "checkout_url": checkout_url,
        "payment_id": str(record.id),
        "mode": provider,
        "forced": force,
    }


def _create_stripe_checkout(
    api_key: str,
    *,
    amount_cents: int,
    business: Business,
    appointment: Appointment,
    service_name: str | None,
) -> tuple[str | None, str | None]:
    """Crée une Checkout Session Stripe (acompte). Renvoie (url, session_id).

    Tolérant : toute erreur Stripe (clé invalide, réseau) retombe en mode manuel
    sans casser la réservation — le RDV reste pris, l'acompte est juste suivi à la main.
    """
    try:
        import stripe

        stripe.api_key = api_key
        settings = get_settings()
        base = (settings.app_base_url or "").rstrip("/") or "https://app.jenny.ai"
        label = service_name or appointment.title or "Prestation"
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=f"{base}/book/merci?dep={appointment.id}",
            cancel_url=f"{base}/book/annule?dep={appointment.id}",
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": f"Acompte — {label}"},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "business_id": str(business.id),
                "appointment_id": str(appointment.id),
                "kind": "deposit",
            },
        )
        return session.url, session.id
    except Exception as exc:  # pragma: no cover - dépend de Stripe/réseau
        logger.warning("deposit.stripe_failed", error=str(exc))
        return None, None


async def mark_deposit_paid_by_payment(
    db: AsyncSession, *, payment: PaymentRecord
) -> Appointment | None:
    """Marque l'acompte payé et confirme le RDV associé. Renvoie le RDV, ou None.

    Idempotent : si déjà payé, ne re-confirme pas inutilement.
    """
    from jenny.domain.models.appointment import Appointment

    payment.status = "paid"
    meta = payment.metadata_ or {}
    appt_id = meta.get("appointment_id")
    if not appt_id:
        return None
    appt = await db.get(Appointment, UUID(str(appt_id)))
    if appt is None:
        return None
    appt.deposit_status = "paid"
    # Un acompte réglé vaut confirmation du créneau.
    if appt.status == "scheduled":
        appt.status = "confirmed"
    logger.info("deposit.paid", appointment_id=str(appt.id))
    return appt
