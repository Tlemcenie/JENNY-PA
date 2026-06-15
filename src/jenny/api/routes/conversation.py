"""Routes API pour le moteur conversationnel.

Endpoint principal qui reçoit un message client,
le fait passer par tout le pipeline Jenny
(intention → entités → agent → réponse),
et retourne la réponse générée.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from jenny.api.dependencies import DbSession  # noqa: TC001 — résolu au runtime par FastAPI
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.message import Message
from jenny.engine.conversation_engine import EngineRequest, EngineResponse
from jenny.engine.factory import get_engine

logger = get_logger(__name__)

router = APIRouter(prefix="/conversation", tags=["Conversation"])


def _enforce_tenant(request: Request, business_id: UUID) -> None:
    """Si l'auth est requise, le business ciblé doit correspondre au contexte JWT."""
    settings = get_settings()
    if not settings.require_auth:
        return
    ctx_bid = getattr(request.state, "business_id", None)
    if ctx_bid is not None and str(ctx_bid) != str(business_id):
        raise HTTPException(status_code=403, detail="Accès refusé pour ce business")


async def _persist_chat(db, body: ConversationRequest, result: EngineResponse) -> None:
    """Persiste la conversation et les messages (client + Jenny) en base.

    Robuste : une erreur de persistance n'empêche pas de renvoyer la réponse
    (le chat reste fonctionnel), mais elle est loggée pour investigation.
    """
    try:
        now = datetime.now(UTC)
        channel = body.channel or "api"

        conv = await db.get(Conversation, body.conversation_id)
        if conv is None:
            conv = Conversation(
                id=body.conversation_id,
                business_id=body.business_id,
                customer_id=body.customer_id,
                channel=channel,
                status="open",
                current_intent=result.intent,
                message_count=0,
                last_message_at=now,
            )
            db.add(conv)
            await db.flush()
        else:
            conv.current_intent = result.intent
            conv.last_message_at = now

        db.add(
            Message(
                conversation_id=conv.id,
                business_id=body.business_id,
                customer_id=body.customer_id,
                external_message_id=str(uuid4()),
                channel=channel,
                direction="inbound",
                content_text=body.message,
                language=body.language,
                status="received",
                intent_label=result.intent,
                received_at=now,
                source_created_at=now,
            )
        )
        db.add(
            Message(
                conversation_id=conv.id,
                business_id=body.business_id,
                external_message_id=str(uuid4()),
                channel=channel,
                direction="outbound",
                sender_name="Jenny",
                content_text=result.response_text,
                language=body.language,
                status="responded",
                received_at=now + timedelta(milliseconds=1),
                source_created_at=now,
            )
        )
        conv.message_count = (conv.message_count or 0) + 2
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("conversation.persist_error", error=str(e))


# ── Schémas de requête / réponse ──


class ConversationRequest(BaseModel):
    """Requête vers le moteur conversationnel."""

    conversation_id: UUID
    business_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)
    channel: str = "api"
    customer_id: UUID | None = None
    language: str | None = None


class ConversationResponse(BaseModel):
    """Réponse du moteur conversationnel."""

    response: str
    intent: str | None = None
    intent_confidence: float = 0.0
    detected_intents: list[dict] | None = None
    is_multi_intent: bool = False
    needs_clarification: bool = False
    entities: dict[str, str] | None = None
    agent_used: str | None = None
    action_result: dict | None = None
    conversation_phase: str = ""
    requires_human: bool = False
    detected_language: str | None = None
    knowledge_gap: bool = False
    gap_question: str | None = None


# ── Routes ──


@router.post("/chat", response_model=ConversationResponse)
async def chat(
    request: Request,
    body: ConversationRequest,
    db: DbSession,
) -> ConversationResponse:
    """Endpoint principal de conversation.

    Envoie un message au moteur conversationnel Jenny
    et reçoit une réponse intelligente.

    Le moteur :
    1. Récupère le contexte de la conversation
    2. Détecte l'intention du message
    3. Extrait les entités (numéro de commande, date, etc.)
    4. Route vers l'agent approprié
    5. Génère une réponse contextualisée

    La conversation et les messages (client + Jenny) sont persistés en base.
    """
    result = await _run_engine_chat(db, body, request)
    return _to_response(result)


async def _run_engine_chat(
    db, body: ConversationRequest, request: Request
) -> EngineResponse:
    """Cœur partagé : charge le contexte, exécute le moteur, persiste."""
    _enforce_tenant(request, body.business_id)
    engine = get_engine()

    from jenny.services.learning_service import load_customer_context, persist_engine_signals
    from jenny.services.persona_loader import load_business_persona
    from jenny.services.prestation_service import format_catalog, load_active_prestations

    persona, business_name = await load_business_persona(db, body.business_id)
    customer_facts = await load_customer_context(db, body.business_id, body.customer_id)
    catalog = format_catalog(await load_active_prestations(db, body.business_id))

    result: EngineResponse = await engine.process(
        EngineRequest(
            conversation_id=body.conversation_id,
            business_id=body.business_id,
            message_text=body.message,
            channel=body.channel,
            customer_id=body.customer_id,
            language=body.language,
            persona=persona,
            business_name=business_name,
            customer_facts=customer_facts,
            catalog=catalog or None,
        )
    )
    await _persist_chat(db, body, result)
    await persist_engine_signals(
        db,
        business_id=body.business_id,
        customer_id=body.customer_id,
        conversation_id=body.conversation_id,
        channel=body.channel,
        result=result,
    )
    return result


def _to_response(result: EngineResponse) -> ConversationResponse:
    return ConversationResponse(
        response=result.response_text,
        intent=result.intent,
        intent_confidence=result.intent_confidence,
        detected_intents=result.detected_intents,
        is_multi_intent=result.is_multi_intent,
        needs_clarification=result.needs_clarification,
        entities=result.entities,
        agent_used=result.agent_used,
        action_result=result.action_result,
        conversation_phase=result.conversation_phase,
        requires_human=result.requires_human,
        detected_language=result.detected_language,
        knowledge_gap=result.knowledge_gap,
        gap_question=result.gap_question,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: Request, body: ConversationRequest, db: DbSession
) -> StreamingResponse:
    """Variante en streaming (SSE) : la réponse s'affiche au fil de l'eau.

    La réponse complète est d'abord produite ET passée au garde-fou persona
    (jamais « IA », pas de fuite) AVANT diffusion — on diffuse ensuite mot à mot
    pour un rendu vivant, sans jamais risquer de laisser passer une formule
    interdite en milieu de flux.
    """
    result = await _run_engine_chat(db, body, request)

    async def _sse():
        text = result.response_text or ""
        for word in text.split(" "):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            await asyncio.sleep(0.025)
        meta = {
            "done": True,
            "intent": result.intent,
            "action_result": result.action_result,
            "requires_human": result.requires_human,
            "needs_clarification": result.needs_clarification,
            "knowledge_gap": result.knowledge_gap,
        }
        yield f"data: {json.dumps(meta)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status/{conversation_id}")
async def conversation_status(conversation_id: UUID) -> dict:
    """Récupère l'état actuel d'une conversation.

    Retourne les informations de contexte :
    intention, slots remplis, phase, nombre de tours.
    """
    engine = get_engine()
    state = engine.state_manager.get(conversation_id)

    if state is None:
        return {"status": "not_found", "conversation_id": str(conversation_id)}

    return {
        "conversation_id": str(state.conversation_id),
        "phase": state.phase.value,
        "turn_count": state.turn_count,
        "current_intent": state.current_intent,
        "intent_confidence": state.intent_confidence,
        "slots": {k: {"value": v.value, "filled": v.filled} for k, v in state.slots.items()},
        "agent_used": state.agent_used,
        "channel": state.channel,
        "created_at": state.created_at.isoformat(),
    }
