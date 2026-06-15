"""Service du connecteur formulaire.

Orchestre la réception d'une soumission de formulaire :
validation, mapping, ingestion, publication du job de normalisation.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jenny.connectors.forms.mapper import map_form_to_message_in
from jenny.connectors.forms.schema import FormSubmissionPayload
from jenny.core.logging import get_logger
from jenny.services.ingestion_service import IngestionResult, MessageIngestionService

logger = get_logger(__name__)


class FormConnectorService:
    """Service de traitement des soumissions de formulaire.

    Responsabilités :
    1. Valider le payload entrant.
    2. Mapper vers le format canonique MessageIn.
    3. Déléguer au service d'ingestion centralisé.

    L'enfilement du job ARQ de normalisation se fait au niveau de la route,
    APRÈS le commit DB (cf. api/routes/ingest.py).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.ingestion_service = MessageIngestionService(session)

    async def handle_submission(
        self,
        payload: FormSubmissionPayload,
        business_id: UUID,
    ) -> IngestionResult:
        """Traite une soumission de formulaire.

        Args:
            payload: Payload validé du formulaire.
            business_id: ID du business destinataire.

        Returns:
            IngestionResult avec message, conversation et client.

        Raises:
            ValidationError: Si le message est un doublon.
        """
        logger.info(
            "connector.form.received",
            form_id=payload.form_id,
            business_id=str(business_id),
        )

        # 1. Mapper vers MessageIn canonique
        message_in = map_form_to_message_in(payload, business_id)

        # 2. Ingérer via le service central
        result = await self.ingestion_service.ingest(message_in)

        # La normalisation asynchrone (job ARQ) est enfilée par la route APRÈS
        # le commit DB, via BackgroundTasks — l'enfiler ici, dans une transaction
        # non encore committée, ferait courir le worker après un message
        # invisible. Cf. api/routes/ingest.py:_enqueue_normalize_after_ingest.

        logger.info(
            "connector.form.ingested",
            message_id=str(result.message.id),
            conversation_id=str(result.conversation.id),
            is_new_customer=result.is_new_customer,
            is_new_conversation=result.is_new_conversation,
        )

        return result
