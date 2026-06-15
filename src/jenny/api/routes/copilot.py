"""Co-pilote agent : Jenny suggère un brouillon de réponse à un humain.

Quand une conversation est reprise par un membre de l'équipe (escalade), il peut
demander à Jenny un brouillon de réponse au dernier message du client. Le
brouillon passe par tout le moteur (persona, base de connaissances, faits client,
garde-fous) mais n'est JAMAIS envoyé ni persisté : l'agent l'édite et décide.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.core.logging import get_logger
from jenny.engine.conversation_engine import EngineRequest
from jenny.engine.factory import get_engine
from jenny.services.learning_service import load_customer_facts
from jenny.services.persona_loader import load_business_persona

logger = get_logger(__name__)

router = APIRouter(prefix="/copilot", tags=["Copilot"])


class SuggestRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    customer_id: UUID | None = None
    conversation_id: UUID | None = None


class SuggestResponse(BaseModel):
    suggestion: str
    knowledge_gap: bool = False
    requires_human: bool = False
    detected_language: str | None = None


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_reply(
    body: SuggestRequest, db: DbSession, principal: CurrentUser
) -> SuggestResponse:
    """Propose un brouillon de réponse au dernier message d'un client.

    Brouillon uniquement : rien n'est envoyé ni enregistré. L'agent garde la main.
    """
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun business associé")

    engine = get_engine()
    persona, business_name = await load_business_persona(db, bid)
    facts = await load_customer_facts(db, bid, body.customer_id)

    # conversation_id éphémère : on ne pollue pas l'état de la vraie conversation.
    result = await engine.process(
        EngineRequest(
            conversation_id=uuid4(),
            business_id=bid,
            message_text=body.message,
            customer_id=body.customer_id,
            persona=persona,
            business_name=business_name,
            customer_facts=facts,
        )
    )
    logger.info("copilot.suggested", business_id=str(bid), gap=result.knowledge_gap)
    return SuggestResponse(
        suggestion=result.response_text,
        knowledge_gap=result.knowledge_gap,
        requires_human=result.requires_human,
        detected_language=result.detected_language,
    )
