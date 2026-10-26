"""Gestion de l'état conversationnel."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)

# cache mémoire borné (widget)
MEMORY_MAX_STATES = 5000
MEMORY_TTL_SECONDS = 48 * 3600

# verrous oui/nom/téléphone
LATCHES = ("awaiting_confirmation", "awaiting_waitlist", "awaiting_name", "awaiting_phone")
# slots d'une réservation
BOOKING_SLOTS = ("date", "time", "service", "duration", "operation")


def _after(ts: str | None, cut: datetime) -> bool:
    """Message après la coupure ?"""
    try:
        return datetime.fromisoformat(ts or "") > cut
    except (ValueError, TypeError):
        return True


class ConversationPhase(StrEnum):
    """Phase de la conversation."""

    GREETING = "greeting"
    UNDERSTANDING = "understanding"  # collecte intention + entités
    SLOT_FILLING = "slot_filling"  # demande les infos manquantes
    PROCESSING = "processing"  # exécute l'action
    RESPONDING = "responding"  # génère la réponse
    CLOSING = "closing"


@dataclass
class ExtractedSlot:
    """Entité extraite (slot)."""

    name: str
    value: str | None = None
    entity_type: str = ""  # ex. DATE, PHONE
    confidence: float = 0.0
    required: bool = False
    filled: bool = False


@dataclass
class ConversationState:
    """État d'une conversation en cours."""

    # identifiants
    conversation_id: UUID = field(default_factory=uuid4)
    business_id: UUID | None = None
    customer_id: UUID | None = None
    session_id: str = field(default_factory=lambda: str(uuid4()))

    # historique
    message_history: list[dict[str, str]] = field(default_factory=list)
    max_history: int = 20  # garde les N derniers

    # intention
    current_intent: str | None = None
    intent_confidence: float = 0.0
    previous_intents: list[str] = field(default_factory=list)
    # demande en cours de collecte
    pending_intent: str | None = None
    # oui = confirme le RDV
    awaiting_confirmation: bool = False
    # oui = inscrit en attente
    awaiting_waitlist: bool = False
    # prochain message = son nom
    awaiting_name: bool = False
    # prochain numéro = son téléphone
    awaiting_phone: bool = False
    # tour d'armement des verrous
    latch_turns: dict[str, int] = field(default_factory=dict)

    # slots
    slots: dict[str, ExtractedSlot] = field(default_factory=dict)
    # dernière purge des slots
    slots_reset_at: str | None = None
    # créneau du rdv pris
    booked_date: str | None = None
    booked_time: str | None = None

    # phase
    phase: ConversationPhase = ConversationPhase.GREETING
    turn_count: int = 0

    # contexte RAG
    retrieved_documents: list[dict] = field(default_factory=list)

    # réponse
    suggested_response: str | None = None
    agent_used: str | None = None
    action_result: dict | None = None

    # métadonnées
    channel: str = ""
    language: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # persona du business (runtime)
    business_persona: dict | None = None
    business_name: str | None = None
    business_hours_text: str | None = None  # horaires pour le prompt
    business_timezone: str | None = None  # fuseau du salon

    # couche intelligence (runtime)
    detected_language: str | None = None  # code ISO du message
    customer_facts: list[str] = field(default_factory=list)  # faits durables connus
    clarification_instruction: str | None = None  # consigne de clarification
    knowledge_gap: bool = False  # pas de réponse fiable
    business_catalog: str | None = None  # catalogue prestations formaté

    def add_user_message(self, content: str) -> None:
        """Ajoute un message utilisateur."""
        self.message_history.append(
            {
                "role": "user",
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        # Tronquer si trop long
        if len(self.message_history) > self.max_history:
            self.message_history = self.message_history[-self.max_history :]
        self.turn_count += 1
        self.updated_at = datetime.now(UTC)

    def add_assistant_message(self, content: str) -> None:
        """Ajoute une réponse assistant."""
        self.message_history.append(
            {
                "role": "assistant",
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self.message_history) > self.max_history:
            self.message_history = self.message_history[-self.max_history :]
        self.updated_at = datetime.now(UTC)

    def set_intent(self, intent: str, confidence: float) -> None:
        """Met à jour l'intention."""
        if self.current_intent and self.current_intent != intent:
            self.previous_intents.append(self.current_intent)
        self.current_intent = intent
        self.intent_confidence = confidence
        self.phase = ConversationPhase.UNDERSTANDING

    def set_slot(
        self,
        name: str,
        value: str,
        entity_type: str = "",
        confidence: float = 1.0,
    ) -> None:
        """Remplit un slot."""
        self.slots[name] = ExtractedSlot(
            name=name,
            value=value,
            entity_type=entity_type,
            confidence=confidence,
            filled=True,
        )
        self.updated_at = datetime.now(UTC)

    def get_missing_slots(self) -> list[ExtractedSlot]:
        """Slots requis non remplis."""
        return [s for s in self.slots.values() if s.required and not s.filled]

    def has_missing_required_slots(self) -> bool:
        """Manque des infos requises ?"""
        return len(self.get_missing_slots()) > 0

    def drop_missing_placeholders(self) -> None:
        """Oublie les slots requis vides."""
        for name in [k for k, s in self.slots.items() if s.required and not s.filled]:
            del self.slots[name]

    def reset_booking_slots(self) -> None:
        """Purge après une réservation."""
        for name in BOOKING_SLOTS:
            self.slots.pop(name, None)
        self.drop_missing_placeholders()
        self.slots_reset_at = datetime.now(UTC).isoformat()

    def user_messages_since_reset(self, last: int = 6) -> list[str]:
        """Messages client depuis la purge."""
        msgs = [m for m in self.message_history[-last:] if m.get("role") == "user"]
        if self.slots_reset_at:
            cut = datetime.fromisoformat(self.slots_reset_at)
            msgs = [m for m in msgs if _after(m.get("timestamp"), cut)]
        return [m.get("content", "") for m in msgs]

    # verrous à durée limitée

    def arm_latch(self, name: str) -> None:
        """Arme un verrou."""
        setattr(self, name, True)
        self.latch_turns[name] = self.turn_count

    def disarm_latch(self, name: str) -> None:
        """Désarme un verrou."""
        setattr(self, name, False)
        self.latch_turns.pop(name, None)

    def expire_latches(self, max_turns: int) -> list[str]:
        """Désarme les verrous trop vieux."""
        expired = []
        for name in LATCHES:
            if not getattr(self, name):
                self.latch_turns.pop(name, None)
                continue
            armed = self.latch_turns.setdefault(name, self.turn_count)
            if self.turn_count - armed > max_turns:
                self.disarm_latch(name)
                expired.append(name)
        return expired

    def get_context_summary(self) -> str:
        """Résumé du contexte."""
        parts = []
        if self.current_intent:
            parts.append(f"Intention: {self.current_intent} ({self.intent_confidence:.0%})")
        filled = {k: v.value for k, v in self.slots.items() if v.filled}
        if filled:
            parts.append(f"Informations collectées: {filled}")
        missing = self.get_missing_slots()
        if missing:
            parts.append(f"Infos manquantes: {[s.name for s in missing]}")
        parts.append(f"Tour: {self.turn_count}, Phase: {self.phase.value}")
        return " | ".join(parts)

    # sérialisation JSON

    def to_dict(self) -> dict:
        """Sérialise l'état en dict."""
        return {
            "conversation_id": str(self.conversation_id),
            "business_id": str(self.business_id) if self.business_id else None,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "session_id": self.session_id,
            "message_history": self.message_history,
            "max_history": self.max_history,
            "current_intent": self.current_intent,
            "intent_confidence": self.intent_confidence,
            "previous_intents": self.previous_intents,
            "pending_intent": self.pending_intent,
            "awaiting_confirmation": self.awaiting_confirmation,
            "awaiting_waitlist": self.awaiting_waitlist,
            "awaiting_name": self.awaiting_name,
            "awaiting_phone": self.awaiting_phone,
            "latch_turns": dict(self.latch_turns),
            "slots": {
                k: {
                    "name": v.name,
                    "value": v.value,
                    "entity_type": v.entity_type,
                    "confidence": v.confidence,
                    "required": v.required,
                    "filled": v.filled,
                }
                for k, v in self.slots.items()
            },
            "slots_reset_at": self.slots_reset_at,
            "booked_date": self.booked_date,
            "booked_time": self.booked_time,
            "phase": self.phase.value,
            "turn_count": self.turn_count,
            "retrieved_documents": self.retrieved_documents,
            "suggested_response": self.suggested_response,
            "agent_used": self.agent_used,
            "action_result": self.action_result,
            "channel": self.channel,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "business_persona": self.business_persona,
            "business_name": self.business_name,
            "business_hours_text": self.business_hours_text,
            "business_timezone": self.business_timezone,
            "detected_language": self.detected_language,
            "customer_facts": list(self.customer_facts),
            "clarification_instruction": self.clarification_instruction,
            "knowledge_gap": self.knowledge_gap,
            "business_catalog": self.business_catalog,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationState:
        """Reconstruit depuis un dict."""
        state = cls(
            conversation_id=UUID(data["conversation_id"]),
            business_id=UUID(data["business_id"]) if data.get("business_id") else None,
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            session_id=data.get("session_id", str(uuid4())),
            message_history=data.get("message_history", []),
            max_history=data.get("max_history", 20),
            current_intent=data.get("current_intent"),
            intent_confidence=data.get("intent_confidence", 0.0),
            previous_intents=data.get("previous_intents", []),
            pending_intent=data.get("pending_intent"),
            awaiting_confirmation=data.get("awaiting_confirmation", False),
            awaiting_waitlist=data.get("awaiting_waitlist", False),
            awaiting_name=data.get("awaiting_name", False),
            awaiting_phone=data.get("awaiting_phone", False),
            latch_turns={str(k): int(v) for k, v in (data.get("latch_turns") or {}).items()},
            slots_reset_at=data.get("slots_reset_at"),
            booked_date=data.get("booked_date"),
            booked_time=data.get("booked_time"),
            phase=ConversationPhase(data.get("phase", "greeting")),
            turn_count=data.get("turn_count", 0),
            retrieved_documents=data.get("retrieved_documents", []),
            suggested_response=data.get("suggested_response"),
            agent_used=data.get("agent_used"),
            action_result=data.get("action_result"),
            channel=data.get("channel", ""),
            language=data.get("language"),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            business_persona=data.get("business_persona"),
            business_name=data.get("business_name"),
            business_hours_text=data.get("business_hours_text"),
            business_timezone=data.get("business_timezone"),
            detected_language=data.get("detected_language"),
            customer_facts=list(data.get("customer_facts") or []),
            clarification_instruction=data.get("clarification_instruction"),
            knowledge_gap=bool(data.get("knowledge_gap", False)),
            business_catalog=data.get("business_catalog"),
        )
        # reconstruit les slots
        for k, v in data.get("slots", {}).items():
            state.slots[k] = ExtractedSlot(**v)
        return state


def _dumps(state: ConversationState) -> str:
    # default=str : uuid, dates
    return json.dumps(state.to_dict(), ensure_ascii=False, default=str)


class StateCache:
    """Cache LRU + TTL des états."""

    def __init__(
        self,
        max_items: int = MEMORY_MAX_STATES,
        ttl: float = MEMORY_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.ttl = float(ttl)
        self._clock = clock
        # clé -> (dernier accès, état)
        self._data: OrderedDict[str, tuple[float, ConversationState]] = OrderedDict()
        self._lock = threading.Lock()

    def _expired(self, seen: float, now: float) -> bool:
        return self.ttl > 0 and now - seen > self.ttl

    def _prune(self, now: float) -> None:
        # les plus vieux sont devant
        while self._data:
            key, (seen, _) = next(iter(self._data.items()))
            if len(self._data) <= self.max_items and not self._expired(seen, now):
                break
            del self._data[key]

    def get(self, key: str) -> ConversationState | None:
        """État vivant, sinon None."""
        now = self._clock()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            if self._expired(item[0], now):
                del self._data[key]
                return None
            # touché : repart à zéro
            self._data[key] = (now, item[1])
            self._data.move_to_end(key)
            return item[1]

    def __getitem__(self, key: str) -> ConversationState:
        state = self.get(key)
        if state is None:
            raise KeyError(key)
        return state

    def __setitem__(self, key: str, state: ConversationState) -> None:
        now = self._clock()
        with self._lock:
            self._data[key] = (now, state)
            self._data.move_to_end(key)
            self._prune(now)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def pop(self, key: str, default: ConversationState | None = None) -> ConversationState | None:
        """Retire un état."""
        with self._lock:
            item = self._data.pop(key, None)
        return item[1] if item is not None else default

    def clear(self) -> None:
        """Vide le cache."""
        with self._lock:
            self._data.clear()


class StateManager:
    """Gère les états de conversation."""

    # préfixe clés Redis + TTL
    REDIS_PREFIX = "jenny:conv:"
    REDIS_TTL = 3600 * 24  # 24h

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        max_memory_states: int = MEMORY_MAX_STATES,
        memory_ttl: float = MEMORY_TTL_SECONDS,
    ) -> None:
        # borné : un état par visiteur
        self._states = StateCache(max_memory_states, memory_ttl)
        self._redis = None  # client sync
        self._redis_url: str | None = None
        self._aredis = None  # client async
        self._aredis_loop: asyncio.AbstractEventLoop | None = None

        # tente Redis
        if redis_url:
            self._init_redis(redis_url)
        else:
            try:
                from jenny.core.config import get_settings

                settings = get_settings()
                if settings.redis_url:
                    self._init_redis(settings.redis_url)
            except Exception:
                pass

        if self._redis is not None:
            logger.info("state_manager.backend", backend="redis")
        else:
            logger.info("state_manager.backend", backend="memory")

    def _init_redis(self, redis_url: str) -> None:
        """Connexion Redis."""
        try:
            import redis

            client = redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                decode_responses=True,
            )
            # test rapide
            client.ping()
            self._redis = client
            self._redis_url = redis_url
        except Exception as e:
            logger.warning("state_manager.redis_unavailable", error=str(e))
            self._redis = None
            self._redis_url = None

    def _async_client(self):
        """Client async de la boucle."""
        if self._redis_url is None:
            return None
        loop = asyncio.get_running_loop()
        if self._aredis is None or self._aredis_loop is not loop:
            import redis.asyncio as aredis

            self._aredis = aredis.from_url(
                self._redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            self._aredis_loop = loop
        return self._aredis

    def _key(self, key: str) -> str:
        return f"{self.REDIS_PREFIX}{key}"

    def _local_get_or_create(
        self, key: str, conversation_id: UUID, business_id: UUID | None, channel: str
    ) -> ConversationState:
        cached = self._states.get(key)
        if cached is not None:
            return cached
        state = ConversationState(
            conversation_id=conversation_id,
            business_id=business_id,
            channel=channel,
        )
        self._states[key] = state
        logger.info("state.created", conversation_id=key)
        return state

    def _cache_raw(self, key: str, raw: str | None) -> ConversationState | None:
        if not raw:
            return None
        state = ConversationState.from_dict(json.loads(raw))
        self._states[key] = state  # cache local
        return state

    # api sync (compat)

    def get_or_create(
        self,
        conversation_id: UUID,
        business_id: UUID | None = None,
        channel: str = "",
    ) -> ConversationState:
        """Récupère ou crée un état."""
        key = str(conversation_id)

        # 1. essaie Redis
        if self._redis is not None:
            try:
                state = self._cache_raw(key, self._redis.get(self._key(key)))
                if state is not None:
                    return state
            except Exception as e:
                logger.warning("state_manager.redis_get_error", error=str(e))

        # 2. cache mémoire, 3. nouvel état
        return self._local_get_or_create(key, conversation_id, business_id, channel)

    def save(self, state: ConversationState) -> None:
        """Sauvegarde l'état."""
        key = str(state.conversation_id)
        self._states[key] = state

        # persiste dans Redis
        if self._redis is not None:
            try:
                self._redis.setex(self._key(key), self.REDIS_TTL, _dumps(state))
            except Exception as e:
                logger.warning("state_manager.redis_save_error", error=str(e))

    def forget(self, conversation_id: UUID) -> bool:
        """Oublie la copie mémoire seule."""
        # Redis garde l'état
        return self._states.pop(str(conversation_id)) is not None

    def delete(self, conversation_id: UUID) -> None:
        """Supprime un état."""
        key = str(conversation_id)
        self._states.pop(key, None)

        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.delete(self._key(key))

    def get(self, conversation_id: UUID) -> ConversationState | None:
        """Récupère un état existant."""
        key = str(conversation_id)

        # cache mémoire d'abord
        cached = self._states.get(key)
        if cached is not None:
            return cached

        # puis Redis
        if self._redis is not None:
            with contextlib.suppress(Exception):
                return self._cache_raw(key, self._redis.get(self._key(key)))

        return None

    # api async (boucle libre)

    async def aget_or_create(
        self,
        conversation_id: UUID,
        business_id: UUID | None = None,
        channel: str = "",
    ) -> ConversationState:
        """Version async de get_or_create."""
        key = str(conversation_id)
        client = self._async_client()
        if client is not None:
            try:
                state = self._cache_raw(key, await client.get(self._key(key)))
                if state is not None:
                    return state
            except Exception as e:
                logger.warning("state_manager.redis_get_error", error=str(e))
        return self._local_get_or_create(key, conversation_id, business_id, channel)

    async def asave(self, state: ConversationState) -> None:
        """Version async de save."""
        key = str(state.conversation_id)
        self._states[key] = state
        client = self._async_client()
        if client is not None:
            try:
                await client.setex(self._key(key), self.REDIS_TTL, _dumps(state))
            except Exception as e:
                logger.warning("state_manager.redis_save_error", error=str(e))

    async def aget(self, conversation_id: UUID) -> ConversationState | None:
        """Version async de get."""
        key = str(conversation_id)
        cached = self._states.get(key)
        if cached is not None:
            return cached
        client = self._async_client()
        if client is not None:
            with contextlib.suppress(Exception):
                return self._cache_raw(key, await client.get(self._key(key)))
        return None

    async def adelete(self, conversation_id: UUID) -> None:
        """Version async de delete."""
        key = str(conversation_id)
        self._states.pop(key, None)
        client = self._async_client()
        if client is not None:
            with contextlib.suppress(Exception):
                await client.delete(self._key(key))

    async def aclose(self) -> None:
        """Ferme le client async."""
        if self._aredis is not None:
            with contextlib.suppress(Exception):
                await self._aredis.aclose()
        self._aredis = None
        self._aredis_loop = None

    @property
    def backend(self) -> str:
        """Backend utilisé."""
        return "redis" if self._redis is not None else "memory"
