"""Service du connecteur email.

Orchestre la réception d'un email entrant : validation, mapping, ingestion.

Sources d'emails entrants déjà branchées :
- Webhook inbound (SendGrid/Mailgun) : POST /ingest/email/inbound (secret requis).
- Polling IMAP : workers/tasks.py:poll_imap_mailbox (cron du worker ARQ).
L'enfilement de la normalisation se fait côté route/worker, après le commit DB.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jenny.connectors.email.mapper import map_email_to_message_in
from jenny.connectors.email.schema import EmailPayload
from jenny.core.logging import get_logger
from jenny.services.ingestion_service import IngestionResult, MessageIngestionService

logger = get_logger(__name__)


class EmailConnectorService:
    """Service de traitement des emails entrants.

    Responsabilités identiques au FormConnectorService :
    1. Valider le payload entrant.
    2. Mapper vers MessageIn canonique.
    3. Déléguer au service d'ingestion centralisé.
    (L'enfilement du job ARQ de normalisation se fait au niveau route/worker,
    après le commit DB.)

    Améliorations futures encore ouvertes :
    - Gestion des threads email (In-Reply-To, References).
    - Stockage des pièces jointes (S3).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.ingestion_service = MessageIngestionService(session)

    async def handle_email(
        self,
        payload: EmailPayload,
        business_id: UUID,
    ) -> IngestionResult:
        """Traite un email entrant.

        Args:
            payload: Payload validé de l'email.
            business_id: ID du business destinataire.

        Returns:
            IngestionResult avec message, conversation et client.
        """
        logger.info(
            "connector.email.received",
            message_id=payload.message_id,
            from_email=payload.from_email,
            business_id=str(business_id),
        )

        # 1. Mapper vers MessageIn canonique
        message_in = map_email_to_message_in(payload, business_id)

        # 2. Ingérer via le service central
        result = await self.ingestion_service.ingest(message_in)

        # La normalisation asynchrone (job ARQ) est enfilée par la route APRÈS
        # le commit DB, via BackgroundTasks (cf. forms/service.py pour le détail).

        logger.info(
            "connector.email.ingested",
            message_id=str(result.message.id),
            conversation_id=str(result.conversation.id),
        )

        return result
