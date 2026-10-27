"""Routes API pour le moteur conversationnel.

Endpoint principal qui reçoit un message client,
le fait passer par tout le pipeline Jenny
(intention → entités → agent → réponse),
et retourne la réponse générée.

Le chat reste ouvert sans compte (widget public) mais un appel anonyme ne lit
jamais de données : pas de fiche client, pas de reprise d'une conversation
d'un client identifié (sauf client né dans ce chat), statut réduit.
Protection du coût : salon vérifié avant tout, puis limite de débit.

Contrat anonyme (chat et widget) :
- l'appelant ne donne jamais de customer_id (403 sinon) ;
- le serveur lit en base le client rattaché à la conversation et le passe au
  moteur, seulement s'il est né dans ce chat (pas de doublon après une perte
  de l'état moteur) ;
- une conversation du widget (id = uuid5(salon, visitor_id), calculé par le
  serveur) ne se reprend que par le widget ; une autre conversation jamais.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from jenny.api.dependencies import (
    CurrentPrincipal,
    DbSession,
    OptionalUser,
    resolve_business_id,
    soft_principal,
)
from jenny.api.middleware.rate_limit import enforce_business_chat_limit
from jenny.core.events import publish_conversation_event
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.engine.conversation_engine import EngineRequest, EngineResponse
from jenny.engine.factory import aget_engine

logger = get_logger(__name__)

router = APIRouter(prefix="/conversation", tags=["Conversation"])


_FORBIDDEN_CONV = "Conversation inaccessible"
_UNKNOWN_CUSTOMER = "Client inconnu pour ce salon"
# convs créées par le chat
_CHAT_CHANNELS = frozenset({"api", "widget"})
_WIDGET = "widget"
_ADOPT_MARGIN = timedelta(minutes=2)
# routes du widget public
_WIDGET_PREFIX = "/api/v1/public/"
# rafraîchit, sans alerte
_REFRESH_KIND = "update"

# cache court des salons
_SALON_TTL = 30.0
_SALON_MAX = 2048
_salon_cache: OrderedDict[UUID, tuple[float, bool]] = OrderedDict()


def reset_salon_cache() -> None:
    """Vide le cache salons."""
    _salon_cache.clear()


async def _salon_open(db, business_id: UUID) -> bool:
    """Salon existant et actif ?"""
    now = time.monotonic()
    hit = _salon_cache.get(business_id)
    if hit is not None and now - hit[0] < _SALON_TTL:
        return hit[1]
    try:
        active = (
            await db.execute(select(Business.is_active).where(Business.id == business_id))
        ).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - base indispo
        await db.rollback()
        logger.warning("conversation.salon_check_error", error=str(exc))
        return True
    ok = bool(active)
    _salon_cache[business_id] = (now, ok)
    _salon_cache.move_to_end(business_id)
    while len(_salon_cache) > _SALON_MAX:
        _salon_cache.popitem(last=False)
    return ok


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def _customer_business(db, customer_id: UUID | None) -> UUID | None:
    """Salon du client, requête légère."""
    if customer_id is None:
        return None
    return (
        await db.execute(select(Customer.business_id).where(Customer.id == customer_id))
    ).scalar_one_or_none()


async def _born_in(db, conv: Conversation, customer_id: UUID | None) -> bool:
    """Client créé dans ce chat ?"""
    if conv.channel not in _CHAT_CHANNELS or customer_id is None:
        return False
    row = (
        await db.execute(
            select(Customer.business_id, Customer.created_at).where(Customer.id == customer_id)
        )
    ).first()
    if row is None or row.business_id != conv.business_id:
        return False
    born, opened = _aware(row.created_at), _aware(conv.created_at)
    # client plus vieux : refus
    if born is None or opened is None or born < opened - _ADOPT_MARGIN:
        return False
    other = (
        await db.execute(
            select(Conversation.id)
            .where(Conversation.customer_id == customer_id, Conversation.id != conv.id)
            .limit(1)
        )
    ).first()
    return other is None


async def _born_here(db, conv: Conversation) -> bool:
    """Client de la conv né ici ?"""
    return await _born_in(db, conv, conv.customer_id)


@dataclass(frozen=True, slots=True)
class _Access:
    """Droits du tour."""

    principal: CurrentPrincipal | None
    # client connu du serveur
    customer_id: UUID | None = None


async def _anon_customer(db, conv: Conversation | None, state, widget: bool) -> UUID | None:
    """Client qu'un anonyme peut garder."""
    if conv is not None:
        # widget : seulement par lui
        if (conv.channel == _WIDGET) != widget:
            raise HTTPException(403, _FORBIDDEN_CONV)
        # anonyme : pas de client connu
        if conv.customer_id is not None and not await _born_here(db, conv):
            raise HTTPException(403, _FORBIDDEN_CONV)
    linked = conv.customer_id if conv is not None else None
    held = state.customer_id if state is not None else None
    # état moteur sans trace en base
    stray = held is not None and held != linked
    if stray and (conv is None or not await _born_in(db, conv, held)):
        raise HTTPException(403, _FORBIDDEN_CONV)
    return linked or held


async def _guard_conversation(
    db, body: ConversationRequest, principal: CurrentPrincipal | None, *, widget: bool = False
) -> UUID | None:
    """Bloque la reprise d'une conv d'autrui, renvoie le client gardé."""
    engine = await aget_engine()
    state = await engine.state_manager.aget(body.conversation_id)
    if state is not None and state.business_id not in (None, body.business_id):
        raise HTTPException(403, _FORBIDDEN_CONV)
    if principal is None and body.customer_id is not None:
        # anonyme : jamais de fiche
        raise HTTPException(403, _UNKNOWN_CUSTOMER)

    try:
        conv = await db.get(Conversation, body.conversation_id)
        if conv is not None and conv.business_id != body.business_id:
            raise HTTPException(403, _FORBIDDEN_CONV)
        if principal is None:
            return await _anon_customer(db, conv, state, widget)
        cust_biz = await _customer_business(db, body.customer_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - base indispo
        await db.rollback()
        logger.warning("conversation.guard_db_error", error=str(exc))
        return None
    if body.customer_id is not None and cust_biz != body.business_id:
        raise HTTPException(403, _UNKNOWN_CUSTOMER)
    return None


def _from_widget(request: Request) -> bool:
    """Appel du widget public ?"""
    return request.url.path.startswith(_WIDGET_PREFIX)


async def _check_chat_access(db, body: ConversationRequest, request: Request) -> _Access:
    """Salon autorisé + conv sûre."""
    widget = _from_widget(request)
    # widget : toujours anonyme
    principal = None if widget else await soft_principal(request, db)
    resolve_business_id(principal, body.business_id, allow_anonymous=True)
    # salon réel avant quota
    if not await _salon_open(db, body.business_id):
        raise HTTPException(404, "Salon introuvable")
    known = await _guard_conversation(db, body, principal, widget=widget)
    return _Access(principal=principal, customer_id=known)


async def _prepare_public_chat(
    db, body: ConversationRequest, request: Request
) -> ConversationRequest:
    """Règles du chat public."""
    principal = await soft_principal(request, db)
    if principal is None and body.customer_id is not None:
        # anonyme : sans fiche client
        body = body.model_copy(update={"customer_id": None})
    await _check_chat_access(db, body, request)
    # quota salon après les droits
    await enforce_business_chat_limit(body.business_id)
    return body


async def _adopted_customer(db, business_id: UUID, result: EngineResponse) -> UUID | None:
    """Client créé ou repris par le moteur."""
    ar = result.action_result if isinstance(result.action_result, dict) else {}
    # même règle que le moteur
    raw = ar.get("customer_id") if ar.get("named") else None
    if not raw:
        return None
    try:
        cid = UUID(str(raw))
    except (TypeError, ValueError):
        return None
    return cid if await _customer_business(db, cid) == business_id else None


async def _persist_chat(db, body: ConversationRequest, result: EngineResponse) -> str | None:
    """Persiste la conversation et les messages (client + Jenny) en base.

    Robuste : une erreur de persistance n'empêche pas de renvoyer la réponse
    (le chat reste fonctionnel), mais elle est loggée pour investigation.

    Retourne l'id du message SORTANT (réponse de Jenny) pour permettre au client
    de rattacher un feedback 👍/👎 ; ``None`` si la persistance a échoué.
    """
    message_id, _customer_id = await _persist_turn(db, body, result)
    return message_id


async def _persist_turn(
    db, body: ConversationRequest, result: EngineResponse, known: UUID | None = None
) -> tuple[str | None, UUID | None]:
    """Écrit le tour, rattache le client."""
    outbound_id = uuid4()
    try:
        now = datetime.now(UTC)
        channel = body.channel or "api"

        conv = await db.get(Conversation, body.conversation_id)
        if conv is not None and conv.business_id != body.business_id:
            # jamais chez un autre salon
            logger.warning("conversation.persist_cross_business", conversation_id=str(conv.id))
            return None, None
        adopted = await _adopted_customer(db, body.business_id, result)
        if conv is None:
            customer_id = body.customer_id or known or adopted
            conv = Conversation(
                id=body.conversation_id,
                business_id=body.business_id,
                customer_id=customer_id,
                channel=channel,
                status="open",
                current_intent=result.intent,
                message_count=0,
                last_message_at=now,
            )
            db.add(conv)
            await db.flush()
        else:
            customer_id = body.customer_id or conv.customer_id or known or adopted
            conv.current_intent = result.intent
            conv.last_message_at = now
            if conv.customer_id is None and customer_id is not None:
                # droit à l'oubli : tout rattacher
                conv.customer_id = customer_id
                await db.execute(
                    update(Message)
                    .where(
                        Message.conversation_id == conv.id,
                        Message.business_id == body.business_id,
                        Message.customer_id.is_(None),
                    )
                    .values(customer_id=customer_id)
                )
                logger.info(
                    "conversation.customer_attached",
                    conversation_id=str(conv.id),
                    customer_id=str(customer_id),
                )

        db.add(
            Message(
                conversation_id=conv.id,
                business_id=body.business_id,
                customer_id=customer_id,
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
                id=outbound_id,
                conversation_id=conv.id,
                business_id=body.business_id,
                customer_id=customer_id,
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
        return str(outbound_id), customer_id
    except Exception as e:
        await db.rollback()
        logger.error("conversation.persist_error", error=str(e))
        return None, None


def _notify_refresh(body: ConversationRequest) -> None:
    """Dashboard à jour, pas d'alerte."""
    publish_conversation_event(
        body.business_id,
        conversation_id=body.conversation_id,
        kind=_REFRESH_KIND,
        channel=body.channel or "api",
    )


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
    # Id du message sortant persisté → permet au client d'attacher un feedback 👍/👎.
    message_id: str | None = None


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
    body = await _prepare_public_chat(db, body, request)
    result, message_id = await _run_engine_chat(db, body, request)
    if message_id is not None:
        _notify_refresh(body)
    return _to_response(result, message_id)


async def _run_engine_chat(
    db, body: ConversationRequest, request: Request, on_token=None
) -> tuple[EngineResponse, str | None]:
    """Cœur partagé : charge le contexte, exécute le moteur, persiste.

    ``on_token`` (optionnel) reçoit chaque token de la réponse au fil de l'eau.
    """
    access = await _check_chat_access(db, body, request)
    # anonyme : client lu en base
    customer_id = body.customer_id or access.customer_id
    engine = await aget_engine()

    from jenny.services.learning_service import load_customer_context, persist_engine_signals
    from jenny.services.persona_loader import load_business_persona
    from jenny.services.prestation_service import format_catalog, load_active_prestations

    persona, business_name = await load_business_persona(db, body.business_id)
    customer_facts = await load_customer_context(db, body.business_id, body.customer_id)
    prestations = await load_active_prestations(db, body.business_id)
    catalog = format_catalog(prestations)

    # horaires réels pour le prompt (best-effort, comme la persona)
    from jenny.engine.business_hours import format_hours

    hours_text: str | None = None
    tz: str | None = None
    try:
        _biz = await db.get(Business, body.business_id)
        hours_text = format_hours(_biz.business_hours if _biz else None)
        # fuseau du salon
        tz = _biz.timezone if _biz else None
    except Exception:  # pragma: no cover - DB best-effort
        hours_text = None
    services = [p.name for p in prestations] or None
    # rend la connexion avant le LLM
    await db.commit()

    result: EngineResponse = await engine.process(
        EngineRequest(
            conversation_id=body.conversation_id,
            business_id=body.business_id,
            message_text=body.message,
            channel=body.channel,
            customer_id=customer_id,
            language=body.language,
            persona=persona,
            business_name=business_name,
            customer_facts=customer_facts,
            catalog=catalog or None,
            catalog_services=services,
            hours_text=hours_text,
            timezone=tz,
        ),
        on_token=on_token,
    )
    message_id, attached = await _persist_turn(db, body, result, known=access.customer_id)
    await persist_engine_signals(
        db,
        business_id=body.business_id,
        customer_id=attached or customer_id,
        conversation_id=body.conversation_id,
        channel=body.channel,
        result=result,
    )
    return result, message_id


def _to_response(result: EngineResponse, message_id: str | None = None) -> ConversationResponse:
    return ConversationResponse(
        message_id=message_id,
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
    """Variante en streaming (SSE) : VRAI token-streaming.

    Les tokens du LLM sont relayés au client dès qu'ils arrivent (premier token
    rapide → Jenny « répond » tout de suite). Le moteur produit en parallèle la
    version FINALE nettoyée (garde-fou persona : jamais « IA », pas de fuite),
    envoyée à la fin via le champ ``text`` — le client remplace alors l'affichage
    brut par cette version sûre. En cas de pépin de flux, repli automatique.
    """
    # contrôles avant le flux
    body = await _prepare_public_chat(db, body, request)
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(tok: str) -> None:
        await queue.put({"token": tok})

    async def run() -> None:
        try:
            result, message_id = await _run_engine_chat(db, body, request, on_token=on_token)
            if message_id is not None:
                _notify_refresh(body)
            await queue.put({"__result__": result, "__message_id__": message_id})
        except Exception as exc:  # pragma: no cover - chemin d'erreur réseau
            logger.error("conversation.stream_error", error=str(exc))
            await queue.put({"__error__": str(exc)})
        finally:
            await queue.put(None)  # sentinelle de fin

    task = asyncio.create_task(run())

    async def _sse():
        result: EngineResponse | None = None
        message_id: str | None = None
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if "token" in item:
                    yield f"data: {json.dumps({'token': item['token']})}\n\n"
                elif "__result__" in item:
                    result = item["__result__"]
                    message_id = item.get("__message_id__")
                elif "__error__" in item:
                    yield f"data: {json.dumps({'error': True})}\n\n"
            if result is not None:
                meta = {
                    "done": True,
                    "text": result.response_text,  # version finale nettoyée (autorité)
                    "intent": result.intent,
                    "action_result": result.action_result,
                    "requires_human": result.requires_human,
                    "needs_clarification": result.needs_clarification,
                    "knowledge_gap": result.knowledge_gap,
                    "message_id": message_id,  # pour le feedback 👍/👎
                }
                yield f"data: {json.dumps(meta)}\n\n"
        finally:
            await task  # s'assure que la persistance s'est terminée

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status/{conversation_id}")
async def conversation_status(conversation_id: UUID, principal: OptionalUser) -> dict:
    """Récupère l'état actuel d'une conversation (scopé au business courant).

    Retourne les informations de contexte : intention, slots remplis, phase,
    nombre de tours. Isolation multi-tenant : l'état complet n'est révélé qu'au
    salon propriétaire ; un autre salon (ou un compte sans salon) obtient
    « not_found ». Sans token, réponse réduite (phase, tours) : jamais de slots
    (prestation/date/nom du client).
    """
    engine = await aget_engine()
    state = await engine.state_manager.aget(conversation_id)
    not_found = {"status": "not_found", "conversation_id": str(conversation_id)}

    if state is None:
        return not_found

    if principal is None:
        # anonyme : rien de sensible
        return {
            "conversation_id": str(state.conversation_id),
            "phase": state.phase.value,
            "turn_count": state.turn_count,
        }

    if principal.business_id is None or state.business_id != principal.business_id:
        return not_found

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
