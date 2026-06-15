"""Mapper formulaire → MessageIn canonique.

Transforme un FormSubmissionPayload en MessageIn,
le format unique que le service d'ingestion accepte.
"""

from datetime import UTC, datetime
from uuid import UUID

from jenny.connectors.forms.schema import FormSubmissionPayload
from jenny.domain.schemas.message import MessageIn


def map_form_to_message_in(
    payload: FormSubmissionPayload,
    business_id: UUID,
) -> MessageIn:
    """Transforme une soumission de formulaire en MessageIn canonique.

    Args:
        payload: Payload brut du formulaire.
        business_id: ID du business destinataire.

    Returns:
        MessageIn prêt pour le service d'ingestion.
    """
    # ID externe unique : form:{form_id}:{timestamp ISO}
    external_id = f"form:{payload.form_id}:{payload.submitted_at.isoformat()}"

    return MessageIn(
        external_message_id=external_id,
        external_conversation_id=None,  # Les formulaires n'ont pas de notion de thread
        channel="form",
        direction="inbound",
        business_id=business_id,
        sender_name=payload.full_name,
        sender_email=payload.email,
        sender_phone=payload.phone,
        subject=payload.subject,
        content_text=payload.message,
        source_created_at=payload.submitted_at,
        received_at=datetime.now(UTC),
        metadata={
            "form_id": payload.form_id,
            "page_url": payload.page_url,
            **payload.metadata,
        },
    )
