"""Gestionnaire d'état conversationnel multi-tour.

Conserve le contexte d'une conversation en cours :
- historique des messages récents,
- intention courante,
- entités extraites (slots),
- informations manquantes,
- état d'avancement de la demande.

Permet aux agents de savoir où on en est dans un échange multi-tour.

Persistence :
- Redis si disponible (prod) — survit aux redémarrages
- Mémoire sinon (dev) — fallback automatique
"""

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
    UNDERSTANDING = "understanding"  # On collecte l'intention + entités
    SLOT_FILLING = "slot_filling"  # On demande les infos manquantes
    PROCESSING = "processing"  # On exécute l'action / recherche
    RESPONDING = "responding"  # On génère la réponse
    CLOSING = "closing"


@dataclass
class ExtractedSlot:
    """Entité extraite (slot) avec sa valeur et son statut."""

    name: str
    value: str | None = None
    entity_type: str = ""  # ORDER_NUMBER, DATE, PHONE, etc.
    confidence: float = 0.0
    required: bool = False
    filled: bool = False


@dataclass
class ConversationState:
    """État complet d'une conversation en cours.

    C'est l'objet central qui transite entre les composants du moteur.
    Il accumule le contexte au fil des échanges multi-tour.
    """

    # ── Identifiants ──
    conversation_id: UUID = field(default_factory=uuid4)
    business_id: UUID | None = None
    customer_id: UUID | None = None
    session_id: str = field(default_factory=lambda: str(uuid4()))

    # ── Historique ──
    message_history: list[dict[str, str]] = field(default_factory=list)
    max_history: int = 20  # Garder les N derniers messages

    # ── Intention ──
    current_intent: str | None = None
    intent_confidence: float = 0.0
    previous_intents: list[str] = field(default_factory=list)
    # Action en cours de collecte d'infos (slot-filling multi-tours) : tant qu'elle
    # est posée, les messages suivants complètent CETTE demande (ex. RDV coiffeur).
    pending_intent: str | None = None
    # Un RDV vient d'être réservé → un « oui » du client le CONFIRME.
    awaiting_confirmation: bool = False
    # Salon complet : Jenny a proposé la liste d'attente → un « oui » INSCRIT le client.
    awaiting_waitlist: bool = False
    # RDV pris pour un client sans nom → le prochain message est son NOM à enregistrer.
    awaiting_name: bool = False
    # Fiche créée sans téléphone → le prochain message contenant un numéro est
    # son TÉLÉPHONE de rappel à enregistrer.
    awaiting_phone: bool = False

    # ── Entités / Slots ──
    slots: dict[str, ExtractedSlot] = field(default_factory=dict)

    # ── Phase ──
    phase: ConversationPhase = ConversationPhase.GREETING
    turn_count: int = 0

    # ── Contexte RAG ──
    retrieved_documents: list[dict] = field(default_factory=list)

    # ── Réponse ──
    suggested_response: str | None = None
    agent_used: str | None = None
    action_result: dict | None = None

    # ── Métadonnées ──
    channel: str = ""
    language: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # ── Cerveau de Jenny (persona configurable, runtime — non sérialisé) ──
    # {"tone": "cool", "tutoiement": true, "vocab": [...], "rules": [{label,on}]}.
    # Injecté par requête depuis la config du business ; None = comportement défaut.
    business_persona: dict | None = None
    business_name: str | None = None

    # ── Couche d'intelligence (runtime, recalculé par requête — non sérialisé) ──
    detected_language: str | None = None  # code ISO (fr, en, es…) du message client
    customer_facts: list[str] = field(default_factory=list)  # faits durables connus
    clarification_instruction: str | None = None  # consigne « pose une question »
    knowledge_gap: bool = False  # aucune réponse fiable disponible
    business_catalog: str | None = None  # catalogue prestations formaté (prix/durée)

    def add_user_message(self, content: str) -> None:
        """Ajoute un message utilisateur à l'historique."""
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
        """Ajoute une réponse assistant à l'historique."""
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
        """Met à jour l'intention détectée."""
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
        """Remplit un slot avec une valeur extraite."""
        self.slots[name] = ExtractedSlot(
            name=name,
            value=value,
            entity_type=entity_type,
            confidence=confidence,
            filled=True,
        )
        self.updated_at = datetime.now(UTC)

    def get_missing_slots(self) -> list[ExtractedSlot]:
        """Retourne les slots requis mais non remplis."""
        return [s for s in self.slots.values() if s.required and not s.filled]

    def has_missing_required_slots(self) -> bool:
        """Vérifie s'il manque des informations requises."""
        return len(self.get_missing_slots()) > 0

    def get_context_summary(self) -> str:
        """Génère un résumé du contexte pour le LLM."""
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

    # ── Sérialisation JSON (pour Redis) ──

    def to_dict(self) -> dict:
        """Sérialise l'état en dict JSON-compatible."""
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
        """Reconstruit un état depuis un dict (depuis Redis)."""
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
        # Reconstruire les slots
        for k, v in data.get("slots", {}).items():
            state.slots[k] = ExtractedSlot(**v)
        return state


class StateManager:
    """Gestionnaire centralisé des états de conversation.

    Utilise Redis si disponible (survit aux redémarrages),
    sinon fallback en mémoire (dev).
    """

    # Préfixe des clés Redis + TTL
    REDIS_PREFIX = "jenny:conv:"
    REDIS_TTL = 3600 * 24  # 24h

    def __init__(self, redis_url: str | None = None) -> None:
        self._states: dict[str, ConversationState] = {}
        self._redis = None

        # Tenter la connexion Redis
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
        """Initialise la connexion Redis (sync pour le state manager)."""
        try:
            import redis

            self._redis = redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                decode_responses=True,
            )
            # Test rapide
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
        """Récupère ou crée un état de conversation."""
        key = str(conversation_id)

        # 1. Essayer Redis
        if self._redis is not None:
            try:
                raw = self._redis.get(f"{self.REDIS_PREFIX}{key}")
                if raw:
                    data = json.loads(raw)
                    state = ConversationState.from_dict(data)
                    self._states[key] = state  # Cache local
                    return state
            except Exception as e:
                logger.warning("state_manager.redis_get_error", error=str(e))

        # 2. Essayer le cache mémoire
        if key in self._states:
            return self._states[key]

        # 3. Créer un nouvel état
        state = ConversationState(
            conversation_id=conversation_id,
            business_id=business_id,
            channel=channel,
        )
        self._states[key] = state
        logger.info("state.created", conversation_id=key)
        return state

    def save(self, state: ConversationState) -> None:
        """Sauvegarde l'état dans Redis (si dispo) + mémoire."""
        key = str(state.conversation_id)
        self._states[key] = state

        # Persister dans Redis
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
        """Supprime un état de conversation."""
        key = str(conversation_id)
        self._states.pop(key, None)

        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.delete(f"{self.REDIS_PREFIX}{key}")

    def get(self, conversation_id: UUID) -> ConversationState | None:
        """Récupère un état existant."""
        key = str(conversation_id)

        # Cache mémoire d'abord
        if key in self._states:
            return self._states[key]

        # Puis Redis
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
        """Retourne le backend utilisé."""
        return "redis" if self._redis is not None else "memory"
