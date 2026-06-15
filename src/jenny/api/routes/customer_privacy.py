"""RGPD : export et anonymisation des données d'un client.

Donne au salon les outils pour honorer les droits de ses clients :
- ``GET  /customers/{id}/export``    → bundle JSON portable (droit d'accès / portabilité) ;
- ``POST /customers/{id}/anonymize`` → effacement des données personnelles (droit à l'oubli).

Tout est scopé au business du JWT (jamais un id arbitraire), et journalisé (audit).
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.services.audit_service import record_audit
from jenny.services.privacy_service import anonymize_customer, export_customer_data

logger = get_logger(__name__)

router = APIRouter(prefix="/customers", tags=["RGPD"])


@router.get("/{customer_id}/export")
async def export_customer(
    customer_id: UUID, db: DbSession, principal: CurrentUser
) -> Response:
    """Exporte toutes les données d'un client en JSON téléchargeable (RGPD)."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    bundle = await export_customer_data(db, business_id=bid, customer_id=customer_id)
    if bundle is None:
        raise HTTPException(404, "Client introuvable")

    record_audit(
        db,
        business_id=bid,
        actor=principal.email or "Agent",
        action="customer.data_exported",
        entity_type="customer",
        entity_id=customer_id,
        summary="Export RGPD des données du client",
    )
    await db.commit()

    payload = json.dumps(bundle, ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="client-{customer_id}.json"'
        },
    )


@router.post("/{customer_id}/anonymize")
async def anonymize_customer_route(
    customer_id: UUID, db: DbSession, principal: CurrentUser
) -> dict:
    """Anonymise un client (droit à l'effacement) : efface ses données personnelles."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")
    result = await anonymize_customer(db, business_id=bid, customer_id=customer_id)
    if result is None:
        raise HTTPException(404, "Client introuvable")

    if not result.get("already_anonymized"):
        record_audit(
            db,
            business_id=bid,
            actor=principal.email or "Agent",
            action="customer.anonymized",
            entity_type="customer",
            entity_id=customer_id,
            summary="Anonymisation RGPD des données du client",
        )
    await db.commit()
    logger.info("customer.anonymized", business_id=str(bid), customer_id=str(customer_id))
    return result
