"""Webhooks des connecteurs de messagerie.

Chaque webhook est authentifié (HMAC Meta, signature Twitter, secret Snapchat)
et routé vers le salon du compte externe (``channel_accounts``). Le repli sur
``JENNY_DEFAULT_BUSINESS_ID`` n'existe que hors prod ; en prod un message non
routable est journalisé puis ignoré (200, pour que le fournisseur n'insiste pas).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable  # noqa: TC003
from datetime import UTC, datetime
from functools import partial
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jenny.api.dependencies import get_db

# schémas gardés au runtime (FastAPI)
from jenny.connectors.instagram.ingest_bridge import (
    ig_messaging_to_message_in,
    payload_recipient_id,
)
from jenny.connectors.instagram.schema import IGMessaging, IGWebhookPayload
from jenny.connectors.instagram.service import InstagramConnector
from jenny.connectors.snapchat.schema import SnapMessage, SnapWebhookPayload
from jenny.connectors.snapchat.service import SnapchatConnector
from jenny.connectors.twitter.schema import TwitterDMEvent, TwitterWebhookPayload
from jenny.connectors.twitter.service import TwitterConnector
from jenny.connectors.whatsapp.ingest_bridge import message_to_message_in, payload_phone_number_id
from jenny.connectors.whatsapp.schema import WhatsAppMessage, WhatsAppWebhookPayload
from jenny.connectors.whatsapp.service import WhatsAppConnector
from jenny.core.config import Settings, get_settings
from jenny.core.events import publish_conversation_event
from jenny.core.exceptions import ValidationError
from jenny.core.logging import get_logger
from jenny.core.metrics import WEBHOOK_DUPLICATES
from jenny.db.repositories.channel_account_repo import ChannelAccountRepository
from jenny.db.repositories.webhook_delivery_repo import WebhookDeliveryRepository
from jenny.db.session import async_session_factory
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.message import Message
from jenny.domain.schemas.message import MessageIn
from jenny.engine.business_hours import is_open
from jenny.engine.conversation_engine import ConversationEngine, EngineRequest
from jenny.engine.factory import aget_engine
from jenny.integrations.meta_signature import verify_meta_signature
from jenny.services import channel_credentials_service as creds_svc
from jenny.services.ingestion_service import MessageIngestionService
from jenny.services.persona_loader import load_business_persona_fresh

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# session fermée avant les tâches
RouteDb = Annotated[AsyncSession, Depends(get_db, scope="function")]


# les connecteurs

_whatsapp = WhatsAppConnector()
_instagram = InstagramConnector()
_twitter = TwitterConnector()
_snapchat = SnapchatConnector()


def _fallback_business(settings: Settings, channel: str, ref: str | None) -> UUID | None:
    """Salon par défaut, jamais en prod."""
    if settings.is_prod:
        logger.warning("webhook.unroutable", channel=channel, ref=ref)
        return None
    raw = (settings.default_business_id or "").strip()
    if not raw:
        return None
    try:
        business_id = UUID(raw)
    except ValueError:
        logger.error("webhook.default_business_invalid", channel=channel)
        return None
    logger.warning("webhook.default_business_fallback", channel=channel, ref=ref, business_id=raw)
    return business_id


def _secret_ok(given: str | None, expected: str) -> bool:
    """Secret partagé, temps constant."""
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def verify_twitter_signature(body: bytes, header: str | None, consumer_secret: str) -> bool:
    """Signature x-twitter-webhooks-signature."""
    if not header or not consumer_secret or not header.startswith("sha256="):
        return False
    digest = hmac.new(consumer_secret.encode(), body, hashlib.sha256).digest()
    expected = "sha256=" + base64.b64encode(digest).decode()
    return hmac.compare_digest(header.encode(), expected.encode())


# moteur partagé (factory)


async def _get_engine() -> ConversationEngine:
    """moteur partagé, boucle libre."""
    return await aget_engine()


async def _engine_context(business_id, customer_id):
    """charge faits + catalogue + fuseau."""
    from jenny.services.learning_service import load_customer_context
    from jenny.services.prestation_service import format_catalog, load_active_prestations

    try:
        async with async_session_factory() as session:
            facts = await load_customer_context(session, business_id, customer_id)
            prestations = await load_active_prestations(session, business_id)
            catalog = format_catalog(prestations)
            # fuseau du salon
            tz = (
                await session.execute(select(Business.timezone).where(Business.id == business_id))
            ).scalar_one_or_none()
        return facts, (catalog or None), ([p.name for p in prestations] or None), tz
    except Exception as e:  # pragma: no cover
        logger.warning("webhook.engine_context_failed", error=str(e))
        return None, None, None, None


async def _persist_engine_signals_safe(
    *, business_id, customer_id, conversation_id, channel, result
):
    """enregistre les signaux moteur."""
    from jenny.services.learning_service import persist_engine_signals

    try:
        async with async_session_factory() as session:
            await persist_engine_signals(
                session,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                channel=channel,
                result=result,
            )
    except Exception as e:  # pragma: no cover
        logger.warning("webhook.persist_signals_failed", error=str(e))


async def _ingest_and_reply(
    channel: str,
    dedup_key: str,
    message_in: MessageIn,
    reply_recipient: str,
    send_reply: Callable[[str, str], Awaitable[bool]],
) -> None:
    """flux commun des webhooks."""
    async with async_session_factory() as session:
        async with session.begin():
            wd_repo = WebhookDeliveryRepository(session)
            if await wd_repo.exists_dedup_key(dedup_key):
                logger.info("webhook.duplicate", channel=channel, dedup_key=dedup_key)
                WEBHOOK_DUPLICATES.labels(channel=channel).inc()
                return
            try:
                ing = await MessageIngestionService(session).ingest(message_in)
            except ValidationError:
                logger.info(
                    "webhook.duplicate_ingest",
                    channel=channel,
                    external_id=message_in.external_message_id,
                )
                WEBHOOK_DUPLICATES.labels(channel=f"{channel}_ingest").inc()
                return
            await wd_repo.record(dedup_key, channel)

        conv_id = ing.conversation.id
        msg_id = ing.message.id
        customer_id = ing.conversation.customer_id
        handled = ing.conversation.assigned_to is not None

    # notifie le dashboard
    publish_conversation_event(
        message_in.business_id, conversation_id=conv_id, kind="inbound", channel=channel
    )

    from jenny.workers.queue import enqueue_normalize_message

    try:
        await enqueue_normalize_message(str(msg_id))
    except Exception as e:
        logger.error("webhook.enqueue_failed", channel=channel, error=str(e))

    # repris par un humain
    if handled:
        logger.info("webhook.human_handled", channel=channel, conversation_id=str(conv_id))
        return

    # hors horaires : auto-réponse
    if await _outside_hours_auto_reply(
        message_in.business_id, conv_id, channel, reply_recipient, send_reply
    ):
        return

    # indicateur de frappe
    publish_conversation_event(
        message_in.business_id, conversation_id=conv_id, kind="processing", channel=channel
    )
    persona, business_name = await load_business_persona_fresh(message_in.business_id)
    facts, catalog, services, tz = await _engine_context(message_in.business_id, customer_id)
    try:
        engine = await _get_engine()
        out = await engine.process(
            EngineRequest(
                conversation_id=conv_id,
                business_id=message_in.business_id,
                message_text=message_in.content_text,
                channel=channel,
                customer_id=customer_id,
                persona=persona,
                business_name=business_name,
                customer_facts=facts,
                catalog=catalog,
                catalog_services=services,
                timezone=tz,
            )
        )
        sent = await send_reply(reply_recipient, out.response_text)
        await _persist_outbound_reply(
            conv_id, message_in.business_id, channel, out.response_text, delivered=sent
        )
        await _persist_engine_signals_safe(
            business_id=message_in.business_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel=channel,
            result=out,
        )
    except Exception as e:
        logger.error("webhook.engine_error", channel=channel, error=str(e))


async def _twitter_ingest_and_reply(
    event_data: dict, business_id_str: str, sender_name: str
) -> None:
    """ingestion + réponse Twitter."""
    business_id = UUID(business_id_str)
    event = TwitterDMEvent.model_validate(event_data)
    data = event.message_create.message_data
    if not data.text:
        return
    now = datetime.now(UTC)
    message_in = MessageIn(
        external_message_id=event.id,
        external_conversation_id=f"tw:{data.sender_id}",
        channel="twitter",
        direction="inbound",
        business_id=business_id,
        sender_name=sender_name,
        sender_handle=data.sender_id,
        content_text=data.text.strip() or " ",
        source_created_at=now,
        received_at=now,
        metadata={"twitter": True},
    )
    await _ingest_and_reply(
        "twitter", f"twitter:{event.id}", message_in, data.sender_id, _twitter.send_reply
    )


async def _snapchat_ingest_and_reply(msg_data: dict, business_id_str: str) -> None:
    """ingestion + réponse Snapchat."""
    business_id = UUID(business_id_str)
    msg = SnapMessage.model_validate(msg_data)
    if not msg.text:
        return
    now = datetime.now(UTC)
    message_in = MessageIn(
        external_message_id=msg.id,
        external_conversation_id=f"snap:{msg.sender_id}",
        channel="snapchat",
        direction="inbound",
        business_id=business_id,
        sender_name=msg.sender_display_name or None,
        sender_handle=msg.sender_id,
        content_text=msg.text.strip() or " ",
        source_created_at=now,
        received_at=now,
        metadata={"snapchat": True},
    )
    await _ingest_and_reply(
        "snapchat", f"snapchat:{msg.id}", message_in, msg.sender_id, _snapchat.send_reply
    )


async def _outside_hours_auto_reply(
    business_id: UUID,
    conversation_id: UUID,
    channel: str,
    recipient: str,
    send_reply: Callable[[str, str], Awaitable[bool]],
) -> bool:
    """auto-réponse hors horaires."""
    async with async_session_factory() as session:
        biz = await session.get(Business, business_id)
        if biz is None or not biz.auto_reply_message:
            return False
        if is_open(biz.business_hours, biz.timezone):
            return False
        text = biz.auto_reply_message
    sent = await send_reply(recipient, text)
    await _persist_outbound_reply(conversation_id, business_id, channel, text, delivered=sent)
    logger.info(
        "webhook.auto_reply_outside_hours", channel=channel, conversation_id=str(conversation_id)
    )
    return True


async def _persist_outbound_reply(
    conversation_id: UUID,
    business_id: UUID,
    channel: str,
    text: str,
    *,
    delivered: bool,
) -> None:
    """persiste la réponse sortante."""
    try:
        async with async_session_factory() as session, session.begin():
            now = datetime.now(UTC)
            session.add(
                Message(
                    conversation_id=conversation_id,
                    business_id=business_id,
                    external_message_id=str(uuid4()),
                    channel=channel,
                    direction="outbound",
                    sender_name="Jenny",
                    content_text=text,
                    status="responded" if delivered else "failed",
                    received_at=now,
                    source_created_at=now,
                )
            )
            conv = await session.get(Conversation, conversation_id)
            if conv is not None:
                conv.message_count = (conv.message_count or 0) + 1
                conv.last_message_at = now
                conv.last_message_preview = text[:200]
        # notifie le dashboard
        publish_conversation_event(
            business_id, conversation_id=conversation_id, kind="outbound", channel=channel
        )
    except Exception as e:
        # ne doit pas casser le flux
        logger.error("webhook.persist_outbound_failed", channel=channel, error=str(e))


def _augment_for_text_channel(text: str, action_result: dict | None) -> str:
    """Ajoute devis + lien acompte au texte (canaux sans bouton)."""
    if not action_result:
        return text
    blocks: list[str] = []
    # devis : PDF non partageable ici, résumé en texte
    items = action_result.get("items")
    if action_result.get("quote_id") and isinstance(items, list) and items:
        ref = str(action_result.get("reference", "")).strip()
        lines = [f"• {it.get('name', '')} : {float(it.get('price_eur', 0)):g} €" for it in items]
        block = (f"📋 Devis {ref}".rstrip()) + "\n" + "\n".join(lines)
        total = action_result.get("total_eur")
        if total is not None:
            block += f"\nTotal : {float(total):g} € TTC"
        blocks.append(block)
    # acompte : lien Stripe (URL publique)
    dep = action_result.get("deposit")
    if isinstance(dep, dict) and isinstance(dep.get("checkout_url"), str):
        amt = dep.get("amount_eur")
        head = (
            f"💳 Acompte de {float(amt):g} € ici :"
            if amt is not None
            else "💳 Régler l'acompte ici :"
        )
        blocks.append(head + "\n" + dep["checkout_url"])
    if blocks:
        return text.rstrip() + "\n\n" + "\n\n".join(blocks)
    return text


async def _whatsapp_ingest_and_reply(
    msg_data: dict,
    business_id_str: str,
    contact_names: dict[str, str],
) -> None:
    """ingestion + réponse WhatsApp."""
    business_id = UUID(business_id_str)
    msg = WhatsAppMessage.model_validate(msg_data)
    if msg.type != "text" or not msg.text:
        return
    dedup_key = f"whatsapp:{msg.id}"

    async with async_session_factory() as session:
        async with session.begin():
            wd_repo = WebhookDeliveryRepository(session)
            if await wd_repo.exists_dedup_key(dedup_key):
                logger.info("webhook.whatsapp.duplicate", dedup_key=dedup_key)
                WEBHOOK_DUPLICATES.labels(channel="whatsapp").inc()
                return
            ingest = MessageIngestionService(session)
            message_in = message_to_message_in(msg, business_id, contact_names)
            try:
                ing = await ingest.ingest(message_in)
            except ValidationError:
                logger.info("webhook.whatsapp.duplicate_ingest", external_id=msg.id)
                WEBHOOK_DUPLICATES.labels(channel="whatsapp_ingest").inc()
                return
            await wd_repo.record(dedup_key, "whatsapp")

        conv_id = ing.conversation.id
        mid = ing.message.id
        # client résolu à l'ingestion
        customer_id = ing.conversation.customer_id
        handled = ing.conversation.assigned_to is not None
        # identifiants du business
        wa_creds = await creds_svc.resolve(session, business_id, "whatsapp")

    publish_conversation_event(
        business_id, conversation_id=conv_id, kind="inbound", channel="whatsapp"
    )

    from jenny.workers.queue import enqueue_normalize_message

    try:
        await enqueue_normalize_message(str(mid))
    except Exception as e:
        logger.error("webhook.whatsapp.enqueue_failed", error=str(e))

    if handled:
        logger.info("webhook.human_handled", channel="whatsapp", conversation_id=str(conv_id))
        return

    if await _outside_hours_auto_reply(
        business_id, conv_id, "whatsapp", msg.from_, partial(_whatsapp.send_reply, creds=wa_creds)
    ):
        return

    publish_conversation_event(
        business_id, conversation_id=conv_id, kind="processing", channel="whatsapp"
    )
    engine = await _get_engine()
    persona, business_name = await load_business_persona_fresh(business_id)
    facts, catalog, services, tz = await _engine_context(business_id, customer_id)
    req = EngineRequest(
        conversation_id=conv_id,
        business_id=business_id,
        message_text=msg.text.body,
        channel="whatsapp",
        customer_id=customer_id,
        persona=persona,
        business_name=business_name,
        customer_facts=facts,
        catalog=catalog,
        catalog_services=services,
        timezone=tz,
    )
    try:
        out = await engine.process(req)
        reply_text = _augment_for_text_channel(out.response_text, out.action_result)
        sent = await _whatsapp.send_reply(msg.from_, reply_text, creds=wa_creds)
        await _persist_outbound_reply(conv_id, business_id, "whatsapp", reply_text, delivered=sent)
        await _persist_engine_signals_safe(
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel="whatsapp",
            result=out,
        )
    except Exception as e:
        logger.error("webhook.whatsapp.engine_error", error=str(e))


async def _instagram_ingest_and_reply(messaging_data: dict, business_id_str: str) -> None:
    """ingestion + réponse Instagram."""
    business_id = UUID(business_id_str)
    messaging = IGMessaging.model_validate(messaging_data)
    if messaging.message is None or not messaging.message.text:
        return
    mid = messaging.message.mid
    dedup_key = f"instagram:{mid}"

    async with async_session_factory() as session:
        async with session.begin():
            wd_repo = WebhookDeliveryRepository(session)
            if await wd_repo.exists_dedup_key(dedup_key):
                logger.info("webhook.instagram.duplicate", dedup_key=dedup_key)
                WEBHOOK_DUPLICATES.labels(channel="instagram").inc()
                return
            ingest = MessageIngestionService(session)
            message_in = ig_messaging_to_message_in(messaging, business_id)
            try:
                ing = await ingest.ingest(message_in)
            except ValidationError:
                logger.info("webhook.instagram.duplicate_ingest", external_id=mid)
                WEBHOOK_DUPLICATES.labels(channel="instagram_ingest").inc()
                return
            await wd_repo.record(dedup_key, "instagram")

        conv_id = ing.conversation.id
        msg_id = ing.message.id
        customer_id = ing.conversation.customer_id
        handled = ing.conversation.assigned_to is not None
        ig_creds = await creds_svc.resolve(session, business_id, "instagram")

    publish_conversation_event(
        business_id, conversation_id=conv_id, kind="inbound", channel="instagram"
    )

    from jenny.workers.queue import enqueue_normalize_message

    try:
        await enqueue_normalize_message(str(msg_id))
    except Exception as e:
        logger.error("webhook.instagram.enqueue_failed", error=str(e))

    if handled:
        logger.info("webhook.human_handled", channel="instagram", conversation_id=str(conv_id))
        return

    if await _outside_hours_auto_reply(
        business_id,
        conv_id,
        "instagram",
        messaging.sender.id,
        partial(_instagram.send_reply, creds=ig_creds),
    ):
        return

    publish_conversation_event(
        business_id, conversation_id=conv_id, kind="processing", channel="instagram"
    )
    engine = await _get_engine()
    persona, business_name = await load_business_persona_fresh(business_id)
    facts, catalog, services, tz = await _engine_context(business_id, customer_id)
    req = EngineRequest(
        conversation_id=conv_id,
        business_id=business_id,
        message_text=messaging.message.text,
        channel="instagram",
        customer_id=customer_id,
        persona=persona,
        business_name=business_name,
        customer_facts=facts,
        catalog=catalog,
        catalog_services=services,
        timezone=tz,
    )
    try:
        out = await engine.process(req)
        sent = await _instagram.send_reply(messaging.sender.id, out.response_text, creds=ig_creds)
        await _persist_outbound_reply(
            conv_id, business_id, "instagram", out.response_text, delivered=sent
        )
        await _persist_engine_signals_safe(
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel="instagram",
            result=out,
        )
    except Exception as e:
        logger.error("webhook.instagram.engine_error", error=str(e))


# ════════════════════════════════════════════
#  WHATSAPP
# ════════════════════════════════════════════


@router.get("/whatsapp")
async def whatsapp_verify(
    db: RouteDb,
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    """vérif webhook WhatsApp (Meta)."""
    if hub_mode == "subscribe" and await creds_svc.matches_verify_token(
        db, "whatsapp", hub_verify_token
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403, content="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: RouteDb,
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict:
    """réception messages WhatsApp."""
    settings = get_settings()
    body = await request.body()

    if not settings.meta_signature_skipped:
        secret = settings.facebook_app_secret
        if not secret or not verify_meta_signature(body, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        data = json.loads(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    try:
        payload = WhatsAppWebhookPayload.model_validate(data)
    except Exception as e:
        # non géré : acquitté en 200
        logger.warning("webhook.whatsapp.unsupported_payload", error=str(e))
        return {"status": "ignored", "reason": "unsupported_payload"}

    phone_id = payload_phone_number_id(payload)
    if not phone_id:
        return {"status": "ignored", "reason": "no_phone_number_id"}

    ch_repo = ChannelAccountRepository(db)
    business_id = await ch_repo.get_business_for_channel("whatsapp", phone_id)
    if business_id is None:
        business_id = _fallback_business(settings, "whatsapp", phone_id)
    if business_id is None:
        logger.error("webhook.whatsapp.no_business", phone_number_id=phone_id)
        return {"status": "ignored", "reason": "no_channel_account_mapping"}

    count = 0
    for entry in payload.entry:
        for change in entry.changes:
            value = change.value
            contact_map = {
                c.wa_id: (c.profile.name if c.profile and c.profile.name else c.wa_id)
                for c in value.contacts
            }
            for msg in value.messages:
                if msg.type != "text" or msg.text is None:
                    continue
                background_tasks.add_task(
                    _whatsapp_ingest_and_reply,
                    msg.model_dump(by_alias=True),
                    str(business_id),
                    contact_map,
                )
                count += 1

    logger.info("webhook.whatsapp.received", count=count)
    return {"status": "ok"}


# ════════════════════════════════════════════
#  INSTAGRAM
# ════════════════════════════════════════════


@router.get("/instagram")
async def instagram_verify(
    db: RouteDb,
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    """vérif webhook Instagram (Meta)."""
    if hub_mode == "subscribe" and await creds_svc.matches_verify_token(
        db, "instagram", hub_verify_token
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403, content="Verification failed")


@router.post("/instagram")
async def instagram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: RouteDb,
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict:
    """réception DMs Instagram."""
    settings = get_settings()
    body = await request.body()

    if not settings.meta_signature_skipped:
        secret = settings.facebook_app_secret
        if not secret or not verify_meta_signature(body, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        data = json.loads(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    try:
        payload = IGWebhookPayload.model_validate(data)
    except Exception as e:
        logger.warning("webhook.instagram.unsupported_payload", error=str(e))
        return {"status": "ignored", "reason": "unsupported_payload"}

    recipient_id = payload_recipient_id(payload)
    ch_repo = ChannelAccountRepository(db)
    business_id = (
        await ch_repo.get_business_for_channel("instagram", recipient_id) if recipient_id else None
    )
    if business_id is None:
        business_id = _fallback_business(settings, "instagram", recipient_id)
    if business_id is None:
        logger.error("webhook.instagram.no_business", recipient_id=recipient_id)
        return {"status": "ignored", "reason": "no_channel_account_mapping"}

    count = 0
    for entry in payload.entry:
        for messaging in entry.messaging:
            if messaging.message is None or not messaging.message.text:
                continue
            background_tasks.add_task(
                _instagram_ingest_and_reply,
                messaging.model_dump(),
                str(business_id),
            )
            count += 1

    logger.info("webhook.instagram.received", count=count)
    return {"status": "ok"}


# ════════════════════════════════════════════
#  TWITTER / X
# ════════════════════════════════════════════


@router.get("/twitter")
async def twitter_crc(
    crc_token: str = Query("", description="CRC token envoyé par Twitter"),
) -> dict:
    """vérif CRC Twitter."""
    response_token = _twitter.compute_crc_response(crc_token)
    return {"response_token": response_token}


@router.post("/twitter")
async def twitter_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: RouteDb,
) -> dict:
    """réception DMs Twitter (signée)."""
    settings = get_settings()
    body = await request.body()
    secret = settings.twitter_api_secret
    if secret:
        sig = request.headers.get("x-twitter-webhooks-signature")
        if not verify_twitter_signature(body, sig, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif settings.is_prod:
        # prod : signature obligatoire
        raise HTTPException(status_code=503, detail="Webhook Twitter non configuré")
    else:
        logger.warning("webhook.twitter.unsigned_dev")
    try:
        data = json.loads(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    try:
        payload = TwitterWebhookPayload.model_validate(data)
    except Exception as e:
        logger.warning("webhook.twitter.unsupported_payload", error=str(e))
        return {"status": "ignored", "reason": "unsupported_payload"}

    ch_repo = ChannelAccountRepository(db)
    business_id = (
        await ch_repo.get_business_for_channel("twitter", payload.for_user_id)
        if payload.for_user_id
        else None
    )
    if business_id is None:
        business_id = _fallback_business(settings, "twitter", payload.for_user_id)
    if business_id is None:
        return {"status": "ignored", "reason": "no_channel_account_mapping"}

    count = 0
    for event in payload.direct_message_events:
        if event.type != "message_create":
            continue
        data_ = event.message_create.message_data
        if data_.sender_id == payload.for_user_id or not data_.text:
            continue  # pas nos DM ni vides
        user = payload.users.get(data_.sender_id)
        sender_name = f"@{user.screen_name}" if user else data_.sender_id
        background_tasks.add_task(
            _twitter_ingest_and_reply, event.model_dump(), str(business_id), sender_name
        )
        count += 1

    logger.info("webhook.twitter.received", count=count)
    return {"status": "ok"}


# ════════════════════════════════════════════
#  SNAPCHAT
# ════════════════════════════════════════════


@router.post("/snapchat")
async def snapchat_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: RouteDb,
    x_jenny_webhook_secret: Annotated[str | None, Header(alias="X-Jenny-Webhook-Secret")] = None,
) -> dict:
    """réception messages Snapchat (secret partagé)."""
    settings = get_settings()
    if not settings.snapchat_webhook_secret:
        # pas de secret : fermé
        raise HTTPException(status_code=503, detail="Webhook Snapchat non configuré")
    if not _secret_ok(x_jenny_webhook_secret, settings.snapchat_webhook_secret):
        raise HTTPException(status_code=401, detail="Secret webhook invalide")
    body = await request.body()
    try:
        data = json.loads(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    try:
        payload = SnapWebhookPayload.model_validate(data)
    except Exception as e:
        logger.warning("webhook.snapchat.unsupported_payload", error=str(e))
        return {"status": "ignored", "reason": "unsupported_payload"}

    business_id = (
        await ChannelAccountRepository(db).get_business_for_channel("snapchat", payload.app_id)
        if payload.app_id
        else None
    )
    if business_id is None:
        business_id = _fallback_business(settings, "snapchat", payload.app_id or None)
    if business_id is None:
        return {"status": "ignored", "reason": "no_channel_account_mapping"}

    count = 0
    for msg in payload.messages:
        if not msg.text:
            continue
        background_tasks.add_task(_snapchat_ingest_and_reply, msg.model_dump(), str(business_id))
        count += 1

    logger.info("webhook.snapchat.received", count=count)
    return {"status": "ok"}


# ════════════════════════════════════════════
#  HEALTH CHECK TOUS LES CANAUX
# ════════════════════════════════════════════


@router.get("/health")
async def webhooks_health() -> dict:
    """état des canaux."""
    return {
        "whatsapp": await _whatsapp.health_check(),
        "instagram": await _instagram.health_check(),
        "twitter": await _twitter.health_check(),
        "snapchat": await _snapchat.health_check(),
    }
