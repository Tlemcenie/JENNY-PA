"""Chat public du widget, sans compte."""

from __future__ import annotations

import re
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from jenny.api.dependencies import DbSession  # noqa: TC001
from jenny.api.middleware.rate_limit import _client_ip
from jenny.api.routes.conversation import _run_engine_chat
from jenny.core.config import get_settings
from jenny.core.events import publish_conversation_event
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.message import Message

if TYPE_CHECKING:
    from jenny.engine.conversation_engine import EngineResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/public/chat", tags=["Public chat"])

CHANNEL = "widget"
MAX_MESSAGE = 1000
MAX_BODY = 16 * 1024
DEFAULT_COLOR = "#FF7F6A"
# namespace fixe, ne pas changer
_NS = UUID("6f0c7a52-3b1e-4d8a-9c55-1e2f7a9b4c10")
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
# bidi trompeurs
_BIDI = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}


# ── limiteur mémoire ──


class _Window:
    """Fenêtre glissante en mémoire, bornée."""

    def __init__(self, limit: int, seconds: float, max_keys: int = 5000) -> None:
        self.limit = limit
        self.seconds = seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def wait(self, key: str, now: float) -> int:
        """Secondes à attendre, 0 si ok."""
        dq = self._hits.get(key)
        if not dq:
            return 0
        cutoff = now - self.seconds
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) < self.limit:
            return 0
        return max(1, int(dq[0] + self.seconds - now) + 1)

    def add(self, key: str, now: float) -> None:
        """Compte une requête."""
        dq = self._hits.get(key)
        if dq is None:
            dq = deque()
            self._hits[key] = dq
            # vire les plus vieux
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        dq.append(now)

    def clear(self) -> None:
        """Vide tout."""
        self._hits.clear()


_VISITOR = _Window(10, 60)
_IP = _Window(30, 60)
_SALON = _Window(600, 600, max_keys=2000)
_POLL_VISITOR = _Window(20, 60)
_POLL_IP = _Window(120, 60)
_CONFIG_IP = _Window(60, 60)
_LIMITS = (_VISITOR, _IP, _SALON, _POLL_VISITOR, _POLL_IP, _CONFIG_IP)
# conversations en cours
_BUSY: set[UUID] = set()


def reset_limits() -> None:
    """Remet les compteurs à zéro."""
    for w in _LIMITS:
        w.clear()
    _BUSY.clear()


def _limits_on() -> bool:
    return get_settings().rate_limit_enabled


def _take(checks: list[tuple[_Window, str]]) -> int:
    """Vérifie puis compte, tout ou rien."""
    if not _limits_on():
        return 0
    now = time.monotonic()
    wait = max(w.wait(k, now) for w, k in checks)
    if wait:
        return wait
    for w, k in checks:
        w.add(k, now)
    return 0


def _too_many(wait: int, text: str | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "detail": text or f"Trop de messages d'un coup, réessayez dans {wait} s.",
            "retry_after": wait,
        },
        status_code=429,
        headers={"Retry-After": str(wait)},
    )


# ── helpers ──


def conversation_id_for(business_id: UUID, visitor_id: str) -> UUID:
    """Id de conversation stable par visiteur."""
    return uuid5(_NS, f"{business_id}:{visitor_id}")


def _clean_text(value: str) -> str:
    """Retire caractères de contrôle."""
    out = "".join(
        c for c in value if c in "\n\t" or (unicodedata.category(c) != "Cc" and c not in _BIDI)
    )
    return out.strip()


async def _read_body(request: Request) -> bytes:
    """Lit le corps, taille bornée."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(413, "Message trop long.")
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "Message trop long.")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse[T: BaseModel](model: type[T], raw: bytes) -> T:
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as exc:
        raise HTTPException(
            422, exc.errors(include_url=False, include_context=False, include_input=False)
        ) from None


def _check_slug(slug: str) -> None:
    """Slug mal formé : 404 direct."""
    if not _SLUG_RE.fullmatch(slug):
        raise HTTPException(404, "Salon introuvable.")


def _ip(request: Request) -> str:
    # clé courte, bornée
    return _client_ip(request)[:64]


async def _salon(db, slug: str) -> Business:
    """Salon actif par slug, sinon 404."""
    _check_slug(slug)
    biz = (await db.execute(select(Business).where(Business.slug == slug))).scalar_one_or_none()
    if biz is None or not biz.is_active:
        raise HTTPException(404, "Salon introuvable.")
    return biz


def _persona(biz: Business) -> dict:
    return biz.persona if isinstance(biz.persona, dict) else {}


def _color(persona: dict) -> str:
    raw = persona.get("widget_color")
    return raw if isinstance(raw, str) and _HEX_RE.fullmatch(raw) else DEFAULT_COLOR


def _greeting(name: str, tu: bool) -> str:
    """Accueil, assistante virtuelle assumée."""
    if tu:
        return (
            f"Salut ! Je suis Jenny, l'assistante virtuelle de {name}. "
            "Je peux répondre à tes questions ou te réserver un créneau."
        )
    return (
        f"Bonjour ! Je suis Jenny, l'assistante virtuelle de {name}. "
        "Je peux répondre à vos questions ou vous réserver un créneau."
    )


_SUGGESTIONS = [
    "Quels sont vos horaires ?",
    "Je voudrais prendre rendez-vous",
    "Combien coûte une coupe ?",
]

# quick replies, même logique que le chat
_SERVICE_WORDS = (
    "coupe",
    "couleur",
    "coloration",
    "balayage",
    "brushing",
    "mèches",
    "soin",
    "prestation",
    "réaliser",
    "coiffure",
)
_ASKS_DAY = re.compile(
    r"quel\s+jour|quand|quelle\s+date|jour vous arrange|disponib|quel moment vous"
)
_ASKS_TIME = re.compile(
    r"quelle?\s+heure|à quelle heure|quel\s+moment|créneau|plutôt le matin|après-?midi"
)
_ASKS_SERVICE = re.compile(r"quelle?\s+(prestation|service|coiffure)|que souhaitez")
_YES_NO = re.compile(
    r"\b(vous voulez|voulez-vous|souhaitez-vous|est-ce que|[çc]a vous (va|convient|dit|tente)"
    r"|je vous (réserve|note|cale|inscris|bloque)|on (part|réserve|cale) sur|c'est bon pour"
    r"|d'accord)\b"
)


def quick_replies(text: str, needs_clarification: bool = False) -> list[str]:
    """Réponses rapides selon la question."""
    if "?" not in text:
        return []
    t = text.lower()
    hits = sum(1 for w in _SERVICE_WORDS if w in t)
    day = bool(_ASKS_DAY.search(t))
    hour = bool(_ASKS_TIME.search(t))
    if not day and not hour and (hits >= 2 or _ASKS_SERVICE.search(t)):
        return ["Une coupe", "Une couleur", "Un balayage"]
    if hour and not day:
        return ["En matinée", "L'après-midi", "En fin de journée"]
    if day:
        return ["Aujourd'hui", "Demain", "Ce samedi"]
    if (_YES_NO.search(t) or needs_clarification) and len(text.strip()) < 120:
        return ["Oui", "Non"]
    return []


# ── schémas ──


class WidgetConfig(BaseModel):
    """Config publique du widget."""

    name: str
    color: str
    greeting: str
    suggestions: list[str]


class PublicChatRequest(BaseModel):
    """Message d'un visiteur."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    visitor_id: str = Field(..., min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE)

    @field_validator("message")
    @classmethod
    def _no_junk(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("message vide")
        return v


class PollRequest(BaseModel):
    """Demande des réponses de l'équipe."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    visitor_id: str = Field(..., min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class QuoteLine(BaseModel):
    name: str
    price_eur: float


class PublicQuote(BaseModel):
    reference: str | None = None
    lines: list[QuoteLine]
    total_eur: float | None = None


class PublicPayment(BaseModel):
    amount_eur: float | None = None
    url: str


class PublicChatResponse(BaseModel):
    """Réponse publique, rien d'interne."""

    response: str
    quick_replies: list[str] = Field(default_factory=list)
    handoff: bool = False
    human: bool = False
    quote: PublicQuote | None = None
    payment: PublicPayment | None = None


class TeamMessage(BaseModel):
    id: str
    text: str
    at: datetime | None = None


class PollResponse(BaseModel):
    human: bool = False
    messages: list[TeamMessage] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _EngineBody:
    """Corps attendu par le moteur."""

    conversation_id: UUID
    business_id: UUID
    message: str
    channel: str = CHANNEL
    customer_id: UUID | None = None
    language: str | None = None


def _num(value) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _public_quote(ar: dict) -> PublicQuote | None:
    """Devis réduit au strict utile."""
    items = ar.get("items")
    if not ar.get("quote_id") or not isinstance(items, list):
        return None
    lines = []
    for it in items[:10]:
        if not isinstance(it, dict):
            continue
        price = _num(it.get("price_eur"))
        name = str(it.get("name") or "").strip()[:80]
        if name and price is not None:
            lines.append(QuoteLine(name=name, price_eur=price))
    if not lines:
        return None
    ref = str(ar.get("reference") or "").strip()[:40] or None
    return PublicQuote(reference=ref, lines=lines, total_eur=_num(ar.get("total_eur")))


def _public_payment(ar: dict) -> PublicPayment | None:
    """Lien d'acompte, https seulement."""
    dep = ar.get("deposit")
    if not isinstance(dep, dict):
        return None
    url = dep.get("checkout_url")
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 2000:
        return None
    return PublicPayment(amount_eur=_num(dep.get("amount_eur")), url=url)


def _to_public(result: EngineResponse) -> PublicChatResponse:
    ar = result.action_result if isinstance(result.action_result, dict) else {}
    text = result.response_text or ""
    return PublicChatResponse(
        response=text,
        quick_replies=quick_replies(text, result.needs_clarification),
        handoff=result.intent == "escalation",
        quote=_public_quote(ar),
        payment=_public_payment(ar),
    )


async def _taken_over(db, conv_id: UUID, business_id: UUID) -> bool:
    """Un humain a repris la main ?"""
    who = (
        await db.execute(
            select(Conversation.assigned_to).where(
                Conversation.id == conv_id, Conversation.business_id == business_id
            )
        )
    ).scalar_one_or_none()
    return bool(who)


async def _save_inbound_only(db, conv_id: UUID, text: str) -> bool:
    """Garde le message, Jenny se tait."""
    try:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            return False
        now = datetime.now(UTC)
        db.add(
            Message(
                conversation_id=conv.id,
                business_id=conv.business_id,
                customer_id=conv.customer_id,
                external_message_id=str(uuid4()),
                channel=CHANNEL,
                direction="inbound",
                content_text=text,
                status="received",
                received_at=now,
                source_created_at=now,
            )
        )
        conv.message_count = (conv.message_count or 0) + 1
        conv.last_message_at = now
        conv.last_message_preview = text[:200]
        await db.commit()
        return True
    except Exception as exc:
        await db.rollback()
        logger.error("public_chat.persist_error", error=str(exc))
        return False


# ── routes ──


@router.get("/{slug}/config", response_model=WidgetConfig)
async def widget_config(
    slug: str, request: Request, response: Response, db: DbSession
) -> WidgetConfig | JSONResponse:
    """Nom, couleur et accueil du widget."""
    _check_slug(slug)
    wait = _take([(_CONFIG_IP, _ip(request))])
    if wait:
        return _too_many(wait, "Trop de requêtes, réessayez dans un instant.")
    biz = await _salon(db, slug)
    persona = _persona(biz)
    name = (biz.name or "votre salon").strip()[:80]
    response.headers["Cache-Control"] = "public, max-age=60"
    return WidgetConfig(
        name=name,
        color=_color(persona),
        greeting=_greeting(name, persona.get("tutoiement") is True),
        suggestions=list(_SUGGESTIONS),
    )


@router.post("/{slug}", response_model=PublicChatResponse)
async def public_chat(
    slug: str, request: Request, db: DbSession
) -> PublicChatResponse | JSONResponse:
    """Message du site vers Jenny."""
    _check_slug(slug)
    body = _parse(PublicChatRequest, await _read_body(request))
    wait = _take([(_VISITOR, f"{slug}:{body.visitor_id}"), (_IP, _ip(request))])
    if wait:
        return _too_many(wait)
    biz = await _salon(db, slug)
    wait = _take([(_SALON, str(biz.id))])
    if wait:
        return _too_many(wait, "Jenny reçoit beaucoup de messages, réessayez dans un instant.")

    conv_id = conversation_id_for(biz.id, body.visitor_id)
    if conv_id in _BUSY:
        return _too_many(2, "Jenny vous répond, un message à la fois.")
    _BUSY.add(conv_id)
    try:
        # reprise humaine : Jenny se tait
        if await _taken_over(db, conv_id, biz.id):
            if await _save_inbound_only(db, conv_id, body.message):
                publish_conversation_event(
                    biz.id, conversation_id=conv_id, kind="inbound", channel=CHANNEL
                )
            return PublicChatResponse(response="", handoff=True, human=True)

        engine_body = _EngineBody(conversation_id=conv_id, business_id=biz.id, message=body.message)
        try:
            result, message_id = await _run_engine_chat(db, engine_body, request)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("public_chat.engine_error", business_id=str(biz.id), error=str(exc))
            raise HTTPException(
                503, "Jenny est indisponible pour le moment, réessayez dans un instant."
            ) from None
    finally:
        _BUSY.discard(conv_id)

    if message_id is not None:
        publish_conversation_event(biz.id, conversation_id=conv_id, kind="inbound", channel=CHANNEL)
    logger.info("public_chat.reply", business_id=str(biz.id), conversation_id=str(conv_id))
    return _to_public(result)


@router.post("/{slug}/poll", response_model=PollResponse)
async def poll_team(slug: str, request: Request, db: DbSession) -> PollResponse | JSONResponse:
    """Réponses de l'équipe pour ce visiteur."""
    _check_slug(slug)
    body = _parse(PollRequest, await _read_body(request))
    wait = _take([(_POLL_VISITOR, f"{slug}:{body.visitor_id}"), (_POLL_IP, _ip(request))])
    if wait:
        return _too_many(wait)
    biz = await _salon(db, slug)
    conv_id = conversation_id_for(biz.id, body.visitor_id)
    human = await _taken_over(db, conv_id, biz.id)
    rows = (
        await db.execute(
            select(Message.id, Message.content_text, Message.received_at, Message.sender_name)
            .where(
                Message.conversation_id == conv_id,
                Message.business_id == biz.id,
                Message.direction == "outbound",
            )
            .order_by(Message.received_at.desc())
            .limit(40)
        )
    ).all()
    team = [
        TeamMessage(id=str(mid), text=(text or "")[:2000], at=at)
        for mid, text, at, sender in reversed(rows)
        if (sender or "") != "Jenny" and (text or "").strip()
    ][-20:]
    return PollResponse(human=human, messages=team)
