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
_VAT_RATE = 0.20  # TVA française standard (prestations de coiffure)


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
            total_cents = sum(int(p.price_cents or 0) for p in matched)  # prix catalogue = TTC
            total_ht_cents = round(total_cents / (1 + _VAT_RATE))
            total_tva_cents = total_cents - total_ht_cents
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
                total_ht_cents=total_ht_cents,
                total_tva_cents=total_tva_cents,
                vat_rate=_VAT_RATE,
                currency="EUR",
                status="draft",
                valid_until=valid_until,
            )
            db.add(quote)

            # Devis PDF (logo + lignes + ventilation HT/TVA/TTC) + email (best-effort).
            emailed = False
            if email:
                emailed = await _send_quote_with_pdf(
                    to=email,
                    customer_name=name,
                    business=business,
                    items=items,
                    reference=reference,
                    vat_rate=_VAT_RATE,
                    valid_until=valid_until,
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


def _eur(cents: int) -> str:
    """Formate des centimes en euros à la française (1 234,50 €)."""
    return f"{cents / 100:,.2f} €".replace(",", " ").replace(".", ",")


def _quote_email_html(
    *,
    business_name: str,
    customer_name: str,
    reference: str,
    items: list[dict],
    vat_rate: float,
    valid_until: dt.datetime,
) -> str:
    """Construit le corps HTML du mail de devis (DA Jenny, lignes + ventilation TVA)."""
    from html import escape

    from jenny.notifications.email_layout import (
        BORDER,
        CARD_SOFT,
        CORAL,
        CREAM,
        MONO,
        MUTED,
        SANS,
    )

    total_ttc = 0
    rows = []
    for it in items:
        ttc = round(float(it.get("price_eur", 0)) * 100)
        total_ttc += ttc
        dur = it.get("duration_minutes")
        dur_txt = f" · {dur} min" if dur else ""
        rows.append(
            f'<tr><td style="padding:11px 0;border-bottom:1px solid {BORDER};'
            f'font-family:{SANS};font-size:14px;color:{CREAM};">{escape(str(it.get("name", "")))}'
            f'<span style="color:{MUTED};font-size:12px;">{dur_txt}</span></td>'
            f'<td align="right" style="padding:11px 0;border-bottom:1px solid {BORDER};'
            f'font-family:{SANS};font-size:14px;color:{CREAM};white-space:nowrap;">{_eur(ttc)}</td></tr>'
        )

    total_ht = round(total_ttc / (1 + vat_rate))
    total_tva = total_ttc - total_ht
    pct = round(vat_rate * 100)

    lignes = "".join(rows)
    return (
        f'<div style="font-family:{SANS};font-size:15px;line-height:1.6;color:{MUTED};margin:0 0 18px;">'
        f"Bonjour {escape(customer_name)},<br><br>"
        f"Voici votre devis <b style=\"color:{CREAM};\">{escape(reference)}</b>. "
        f"Le détail complet est dans le PDF joint."
        f"</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{CARD_SOFT};border:1px solid {BORDER};border-radius:16px;padding:8px 18px;">'
        f"{lignes}"
        f'<tr><td style="padding:12px 0 3px;font-family:{SANS};font-size:13px;color:{MUTED};">Total HT</td>'
        f'<td align="right" style="padding:12px 0 3px;font-family:{SANS};font-size:13px;color:{MUTED};">{_eur(total_ht)}</td></tr>'
        f'<tr><td style="padding:3px 0;font-family:{SANS};font-size:13px;color:{MUTED};">TVA {pct} %</td>'
        f'<td align="right" style="padding:3px 0;font-family:{SANS};font-size:13px;color:{MUTED};">{_eur(total_tva)}</td></tr>'
        f'<tr><td style="padding:8px 0 4px;font-family:{SANS};font-size:16px;font-weight:700;color:{CORAL};">Total TTC</td>'
        f'<td align="right" style="padding:8px 0 4px;font-family:{SANS};font-size:16px;font-weight:700;color:{CORAL};">{_eur(total_ttc)}</td></tr>'
        f"</table>"
        f'<div style="font-family:{MONO};font-size:11px;letter-spacing:1px;color:{MUTED};margin:16px 0 0;text-transform:uppercase;">'
        f"Valable jusqu'au {valid_until.strftime('%d/%m/%Y')}</div>"
        f'<div style="font-family:{SANS};font-size:14px;line-height:1.6;color:{MUTED};margin:18px 0 0;">'
        f"Pour accepter ce devis, répondez simplement à cet email. À très vite&nbsp;!<br>"
        f"<b style=\"color:{CREAM};\">{escape(business_name)}</b></div>"
    )


async def _send_quote_with_pdf(
    *,
    to: str,
    customer_name: str,
    business,
    items: list[dict],
    reference: str,
    vat_rate: float,
    valid_until: dt.datetime,
) -> bool:
    """Génère le devis PDF et l'envoie en pièce jointe (email brandé). Best-effort."""
    try:
        from jenny.notifications.email_layout import render_email
        from jenny.notifications.email_sender import EmailMessage, EmailSender
        from jenny.notifications.quote_pdf import build_quote_pdf

        business_name = getattr(business, "name", None) or "Votre salon"
        business_email = getattr(business, "email", None)
        business_phone = getattr(business, "phone", None)

        pdf = build_quote_pdf(
            reference=reference,
            business_name=business_name,
            business_email=business_email,
            business_phone=business_phone,
            customer_name=customer_name,
            items=items,
            vat_rate=vat_rate,
            valid_until=valid_until,
        )

        content_html = _quote_email_html(
            business_name=business_name,
            customer_name=customer_name,
            reference=reference,
            items=items,
            vat_rate=vat_rate,
            valid_until=valid_until,
        )
        body_html = render_email(
            preheader=f"Votre devis {reference} — {business_name}",
            eyebrow="devis",
            heading="Voici votre",
            accent="devis.",
            content_html=content_html,
            app_name="Jenny",
        )
        body_text = (
            f"Bonjour {customer_name},\n\n"
            f"Voici votre devis {reference}. Le détail complet est dans le PDF joint.\n"
            f"Valable jusqu'au {valid_until.strftime('%d/%m/%Y')}.\n\n"
            f"Pour l'accepter, répondez simplement à cet email.\n{business_name}"
        )

        msg = EmailMessage(
            to=to,
            subject=f"📋 Votre devis {reference} — {business_name}",
            body_text=body_text,
            body_html=body_html,
            attachments=[
                {
                    "filename": f"Devis-{reference}.pdf",
                    "content": pdf,
                    "mimetype": "application/pdf",
                }
            ],
        )
        return await EmailSender().send(msg)
    except Exception as exc:  # pragma: no cover - dépend du SMTP / reportlab
        logger.warning("action.generate_quote.email_failed", error=str(exc))
        return False
