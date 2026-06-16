"""Action : génération d'un VRAI devis (coiffeur).

Calcule le devis depuis le catalogue de prestations réel (prix + durée),
persiste un ``Quote`` en base, et l'envoie par email au client si son adresse
est connue (relais SMTP). Plus aucune simulation : référence, montant et
validité correspondent à un devis réellement enregistré.

Robuste : toute incertitude (prestation inconnue, pas de contexte business)
renvoie un résultat « non abouti » exploité par le slot-filling, sans planter.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar
from uuid import UUID, uuid4

from jenny.actions.base import BaseAction
from jenny.core.logging import get_logger

logger = get_logger(__name__)

_VALIDITY_DAYS = 30


class GenerateQuoteAction(BaseAction):
    """Génère un devis réel à partir du catalogue de prestations."""

    name = "generate_quote"
    description = "Crée un devis réel (catalogue) et l'envoie au client"
    required_params: ClassVar[tuple[str, ...]] = ()

    async def execute(self, params: dict) -> dict:
        business_id = params.get("business_id")
        if not business_id:
            return {"success": False, "message": "Contexte business absent."}
        try:
            return await self._generate(UUID(str(business_id)), params)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement DB
            logger.error("action.generate_quote.error", error=str(exc))
            return {
                "success": False,
                "message": "Devis non finalisé (à confirmer avec l'équipe).",
            }

    async def _generate(self, bid: UUID, params: dict) -> dict:
        from jenny.db.session import async_session_factory
        from jenny.domain.models.business import Business
        from jenny.domain.models.customer import Customer
        from jenny.domain.models.quote import Quote
        from jenny.services.prestation_service import (
            format_catalog,
            load_active_prestations,
            match_prestations,
        )

        requested = (params.get("service") or params.get("product") or "").strip()

        async with async_session_factory() as db:
            business = await db.get(Business, bid)
            prestations = await load_active_prestations(db, bid)

            matched = match_prestations(prestations, requested) if requested else []
            if not matched:
                # Pas de prestation identifiée → on demande laquelle (vrai slot-filling),
                # en proposant le catalogue réel. Aucun devis fantôme n'est créé.
                catalogue = format_catalog(prestations) if prestations else ""
                return {
                    "success": False,
                    "needs_service": True,
                    "message": "Pour quel service souhaitez-vous un devis ?",
                    "catalogue": catalogue,
                }

            items = [
                {
                    "name": p.name,
                    "price_eur": p.price_eur,
                    "duration_minutes": p.duration_minutes,
                }
                for p in matched
            ]
            total_cents = sum(int(p.price_cents or 0) for p in matched)
            service_label = " + ".join(p.name for p in matched)

            # Client : on récupère email/nom réels si on a un customer_id valide.
            customer: Customer | None = None
            raw_cid = params.get("customer_id")
            if raw_cid:
                try:
                    customer = await db.get(Customer, UUID(str(raw_cid)))
                except (ValueError, TypeError):
                    customer = None
            email = (params.get("email") or (customer.email if customer else None) or "").strip() or None
            name = (
                params.get("name")
                or (customer.full_name if customer else None)
                or "client"
            )

            valid_until = dt.datetime.now(dt.UTC) + dt.timedelta(days=_VALIDITY_DAYS)
            reference = f"DEV-{uuid4().hex[:8].upper()}"

            quote = Quote(
                business_id=bid,
                customer_id=customer.id if customer else None,
                reference=reference,
                items=items,
                total_cents=total_cents,
                currency="EUR",
                status="draft",
                valid_until=valid_until,
            )
            db.add(quote)

            # Envoi email (best-effort) si l'adresse est connue.
            emailed = False
            if email:
                emailed = await _send_quote_email(
                    to=email,
                    customer_name=name,
                    business_name=(business.name if business else "Jenny"),
                    service=service_label,
                    total_eur=round(total_cents / 100, 2),
                    valid_until=valid_until,
                    reference=reference,
                )
                if emailed:
                    quote.status = "sent"
                    quote.sent_to_email = email

            await db.commit()
            await db.refresh(quote)

            logger.info(
                "action.generate_quote.ok",
                quote_id=str(quote.id),
                reference=reference,
                total_eur=round(total_cents / 100, 2),
                emailed=emailed,
            )
            total_eur = round(total_cents / 100, 2)
            msg = f"Devis {reference} : {service_label} — {total_eur:.2f} €, valable {_VALIDITY_DAYS} jours."
            if emailed:
                msg += f" Envoyé à {email}."
            return {
                "success": True,
                "message": msg,
                "quote_id": str(quote.id),
                "reference": reference,
                "service": service_label,
                "items": items,
                "total_eur": total_eur,
                "currency": "EUR",
                "validity_days": _VALIDITY_DAYS,
                "emailed": emailed,
                "status": quote.status,
            }


async def _send_quote_email(
    *,
    to: str,
    customer_name: str,
    business_name: str,
    service: str,
    total_eur: float,
    valid_until: dt.datetime,
    reference: str,
) -> bool:
    """Envoie le devis par email (gabarit ``quote_sent``). Best-effort."""
    try:
        from jenny.notifications.email_sender import EmailSender

        return await EmailSender().send_template(
            "quote_sent",
            to,
            {
                "business_name": business_name,
                "customer_name": customer_name,
                "service": service,
                "price": f"{total_eur:.2f} €",
                "validity": valid_until.strftime("%d/%m/%Y"),
                "reference": reference,
            },
        )
    except Exception as exc:  # pragma: no cover - dépend du SMTP
        logger.warning("action.generate_quote.email_failed", error=str(exc))
        return False
