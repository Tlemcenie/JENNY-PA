"""Devis : téléchargement du PDF d'un devis déjà généré.

Le devis (``Quote``) est créé par ``GenerateQuoteAction`` pendant la conversation
(prix d'une prestation → devis). Ici on régénère le PDF brandé à la volée depuis
le devis stocké et on le renvoie en ``application/pdf`` — pour que le chat propose
un vrai document téléchargeable, pas seulement un email.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.customer import Customer
from jenny.domain.models.quote import Quote

logger = get_logger(__name__)

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.get("/{quote_id}/pdf")
async def download_quote_pdf(
    quote_id: UUID, db: DbSession, principal: CurrentUser
) -> Response:
    """Renvoie le PDF d'un devis (scopé au business courant).

    Régénère le document à la volée depuis le devis stocké : rien n'est mis en
    cache sur disque. Le PDF reflète toujours l'état du devis en base.
    """
    if principal.business_id is None:
        raise HTTPException(status_code=403, detail="Devis hors de votre périmètre.")

    quote = await db.get(Quote, quote_id)
    if quote is None or quote.business_id != principal.business_id:
        # Même réponse pour « inexistant » et « autre business » : pas de fuite.
        raise HTTPException(status_code=404, detail="Devis introuvable.")

    business = await db.get(Business, quote.business_id)
    customer_name = "client"
    if quote.customer_id is not None:
        cust = await db.get(Customer, quote.customer_id)
        if cust is not None and (cust.full_name or "").strip():
            customer_name = cust.full_name.strip()

    from jenny.notifications.quote_pdf import build_quote_pdf

    pdf = build_quote_pdf(
        reference=quote.reference,
        business_name=(business.name if business else "Salon"),
        business_email=(business.email if business else None),
        business_phone=(business.phone if business else None),
        customer_name=customer_name,
        items=list(quote.items or []),
        vat_rate=quote.vat_rate,
        valid_until=quote.valid_until,
        created=quote.created_at,
    )
    logger.info("quote.pdf.download", quote_id=str(quote_id), reference=quote.reference)
    filename = f"devis-{quote.reference}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
