"""Chat « assistant du coiffeur » — Jenny côté gérant (authentifié).

Le gérant discute avec Jenny SON assistante : comptes rendus de l'agenda,
blocage de créneaux, ajout d'infos à la base de connaissances, questions libres.
Distinct du chat client (`/conversation/chat`) où Jenny est un membre humain de
l'équipe : ici, transparence totale, et des ACTIONS de gestion réelles.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jenny.api.dependencies import CurrentUser, DbSession
from jenny.services.owner_assistant import handle_owner_message

router = APIRouter(prefix="/owner", tags=["Owner assistant"])


class OwnerChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class OwnerChatResponse(BaseModel):
    response: str
    action: str
    data: dict


@router.post("/chat", response_model=OwnerChatResponse)
async def owner_chat(
    body: OwnerChatRequest, db: DbSession, principal: CurrentUser
) -> OwnerChatResponse:
    """Jenny, l'assistante du gérant : compte rendu, blocage de créneau, ajout KB, Q&R."""
    bid = principal.business_id
    if bid is None:
        raise HTTPException(400, "Aucun salon associé à ce compte")
    result = await handle_owner_message(
        db, business_id=bid, actor=principal.email or "Gérant", message=body.message
    )
    return OwnerChatResponse(
        response=result["response"],
        action=result.get("action", "general"),
        data=result.get("data", {}),
    )
