"""Gestion de l'état conversationnel."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from jenny.core.logging import get_logger

logger = get_logger(__name__)


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

    # slots
    slots: dict[str, ExtractedSlot] = field(default_factory=dict)

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
        data = {
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
        }
        return data

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
        )
        # reconstruit les slots
        for k, v in data.get("slots", {}).items():
            state.slots[k] = ExtractedSlot(**v)
        return state


class StateManager:
    """Gère les états de conversation."""

    # préfixe clés Redis + TTL
    REDIS_PREFIX = "jenny:conv:"
    REDIS_TTL = 3600 * 24  # 24h

    def __init__(self, redis_url: str | None = None) -> None:
        self._states: dict[str, ConversationState] = {}
        self._redis = None

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

            self._redis = redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                decode_responses=True,
            )
            # test rapide
            self._redis.ping()
        except Exception as e:
            logger.warning("state_manager.redis_unavailable", error=str(e))
            self._redis = None

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
                raw = self._redis.get(f"{self.REDIS_PREFIX}{key}")
                if raw:
                    data = json.loads(raw)
                    state = ConversationState.from_dict(data)
                    self._states[key] = state  # cache local
                    return state
            except Exception as e:
                logger.warning("state_manager.redis_get_error", error=str(e))

        # 2. cache mémoire
        if key in self._states:
            return self._states[key]

        # 3. nouvel état
        state = ConversationState(
            conversation_id=conversation_id,
            business_id=business_id,
            channel=channel,
        )
        self._states[key] = state
        logger.info("state.created", conversation_id=key)
        return state

    def save(self, state: ConversationState) -> None:
        """Sauvegarde l'état."""
        key = str(state.conversation_id)
        self._states[key] = state

        # persiste dans Redis
        if self._redis is not None:
            try:
                data = json.dumps(state.to_dict(), ensure_ascii=False)
                self._redis.setex(
                    f"{self.REDIS_PREFIX}{key}",
                    self.REDIS_TTL,
                    data,
                )
            except Exception as e:
                logger.warning("state_manager.redis_save_error", error=str(e))

    def delete(self, conversation_id: UUID) -> None:
        """Supprime un état."""
        key = str(conversation_id)
        self._states.pop(key, None)

        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.delete(f"{self.REDIS_PREFIX}{key}")

    def get(self, conversation_id: UUID) -> ConversationState | None:
        """Récupère un état existant."""
        key = str(conversation_id)

        # cache mémoire d'abord
        if key in self._states:
            return self._states[key]

        # puis Redis
        if self._redis is not None:
            try:
                raw = self._redis.get(f"{self.REDIS_PREFIX}{key}")
                if raw:
                    data = json.loads(raw)
                    state = ConversationState.from_dict(data)
                    self._states[key] = state
                    return state
            except Exception:
                pass

        return None

    @property
    def backend(self) -> str:
        """Backend utilisé."""
        return "redis" if self._redis is not None else "memory"
