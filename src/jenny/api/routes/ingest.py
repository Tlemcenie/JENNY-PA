"""Routes d'ingestion des messages.

Webhooks d'entrée pour les connecteurs :
- POST /ingest/form — soumission de formulaire
- POST /ingest/email — email entrant

Chaque route valide le payload, appelle le connecteur approprié,
et retourne le résultat d'ingestion.

/form et /email exigent un JWT ou une clé API (``X-API-Key``) : le salon est
celui du compte, jamais celui passé en query.
"""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query

from jenny.api.dependencies import CurrentPrincipal, DbSession, OptionalTenant, resolve_business_id
from jenny.connectors.email.schema import EmailPayload
from jenny.connectors.email.service import EmailConnectorService
from jenny.connectors.forms.schema import FormSubmissionPayload
from jenny.connectors.forms.service import FormConnectorService
from jenny.core.config import get_settings
from jenny.core.events import publish_conversation_event
from jenny.core.exceptions import ValidationError
from jenny.core.logging import get_logger
from jenny.domain.schemas.message import MessageResponse
from jenny.services.ingestion_service import IngestionResult

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest")


async def _enqueue_normalize_after_ingest(message_id: str) -> None:
    """Après commit DB : enfile la normalisation (ne fait pas échouer la requête)."""
    try:
        from jenny.workers.queue import enqueue_normalize_message

        await enqueue_normalize_message(message_id)
    except Exception as e:
        logger.error(
            "ingestion.enqueue_normalize_failed",
            message_id=message_id,
            error=str(e),
        )


async def _notify_inbound_after_ingest(
    business_id: str, conversation_id: str, channel: str
) -> None:
    """Après commit DB : pousse l'événement « message entrant » vers le dashboard.

    Tâche ``async`` (pas ``sync``) pour que Starlette l'exécute sur la boucle
    asyncio : la file du bus d'événements (``asyncio.Queue``) n'est pas
    thread-safe.
    """
    publish_conversation_event(
        business_id, conversation_id=conversation_id, kind="inbound", channel=channel
    )


def _target_business(principal: CurrentPrincipal | None, requested: UUID | None) -> UUID:
    """Salon du compte, query ignorée."""
    business_id = resolve_business_id(principal)
    if requested is not None and requested != business_id:
        logger.warning(
            "ingest.business_id_ignored",
            requested=str(requested),
            business_id=str(business_id),
        )
    return business_id


def _to_response(result: IngestionResult) -> MessageResponse:
    """Convertit un IngestionResult en MessageResponse."""
    msg = result.message
    return MessageResponse(
        id=str(msg.id),
        channel=msg.channel,
        direction=msg.direction,
        sender_name=msg.sender_name,
        content=msg.content_text,
        status=msg.status,
        conversation_id=str(msg.conversation_id),
        created_at=msg.created_at,
    )


@router.post("/form", response_model=MessageResponse, status_code=201)
async def ingest_form(
    payload: FormSubmissionPayload,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: OptionalTenant,
    business_id: Annotated[UUID | None, Query(description="Ignoré : salon du compte")] = None,
) -> MessageResponse:
    """Réceptionne une soumission de formulaire.

    Le payload est validé, mappé vers le format canonique,
    puis ingéré en DB avec création automatique du client
    et de la conversation si nécessaire.
    """
    business_id = _target_business(principal, business_id)
    service = FormConnectorService(db)
    try:
        result = await service.handle_submission(payload, business_id)
    except ValidationError as e:
        raise HTTPException(status_code=409, detail=e.message) from e

    background_tasks.add_task(_enqueue_normalize_after_ingest, str(result.message.id))
    background_tasks.add_task(
        _notify_inbound_after_ingest,
        str(result.conversation.business_id),
        str(result.conversation.id),
        result.conversation.channel,
    )
    return _to_response(result)


@router.post("/email", response_model=MessageResponse, status_code=201)
async def ingest_email(
    payload: EmailPayload,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: OptionalTenant,
    business_id: Annotated[UUID | None, Query(description="Ignoré : salon du compte")] = None,
) -> MessageResponse:
    """Réceptionne un email entrant.

    Même flux que le formulaire : validation, mapping canonique,
    ingestion, déduplication, résolution conversation.
    """
    business_id = _target_business(principal, business_id)
    service = EmailConnectorService(db)
    try:
        result = await service.handle_email(payload, business_id)
    except ValidationError as e:
        raise HTTPException(status_code=409, detail=e.message) from e

    background_tasks.add_task(_enqueue_normalize_after_ingest, str(result.message.id))
    background_tasks.add_task(
        _notify_inbound_after_ingest,
        str(result.conversation.business_id),
        str(result.conversation.id),
        result.conversation.channel,
    )
    return _to_response(result)


@router.post("/email/inbound", response_model=MessageResponse, status_code=201)
async def ingest_email_inbound(
    payload: EmailPayload,
    business_id: Annotated[UUID, Query(..., description="ID du business destinataire")],
    background_tasks: BackgroundTasks,
    db: DbSession,
    x_jenny_inbound_secret: Annotated[str | None, Header(alias="X-Jenny-Inbound-Secret")] = None,
) -> MessageResponse:
    """Webhook inbound (SendGrid/Mailgun) : secret header obligatoire en prod."""
    settings = get_settings()
    if not settings.email_inbound_secret:
        raise HTTPException(503, "Inbound email secret non configuré (JENNY_EMAIL_INBOUND_SECRET)")
    if not x_jenny_inbound_secret or not hmac.compare_digest(
        x_jenny_inbound_secret.encode(), settings.email_inbound_secret.encode()
    ):
        raise HTTPException(401, "Secret inbound invalide")

    service = EmailConnectorService(db)
    try:
        result = await service.handle_email(payload, business_id)
    except ValidationError as e:
        raise HTTPException(status_code=409, detail=e.message) from e

    background_tasks.add_task(_enqueue_normalize_after_ingest, str(result.message.id))
    background_tasks.add_task(
        _notify_inbound_after_ingest,
        str(result.conversation.business_id),
        str(result.conversation.id),
        result.conversation.channel,
    )
    return _to_response(result)
