"""Service d'ingestion des messages.

Orchestre le flux canonique d'entrée :
1. Déduplication (external_message_id + channel + business_id)
2. Résolution / création du CustomerProfile
3. Résolution / création de la Conversation
4. Persistance du Message
5. Log de l'événement d'ingestion
6. Publication du job ARQ de normalisation

C'est le point d'entrée unique pour TOUS les connecteurs.
Aucun connecteur n'écrit directement en DB.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from jenny.core.exceptions import ValidationError
from jenny.core.logging import get_logger
from jenny.db.repositories.conversation_repo import ConversationRepository
from jenny.db.repositories.customer_repo import CustomerRepository
from jenny.db.repositories.message_event_repo import MessageEventRepository
from jenny.db.repositories.message_repo import MessageRepository
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.message import Message
from jenny.domain.models.notification import Notification
from jenny.domain.schemas.message import MessageIn
from jenny.engine.sentiment import analyze_sentiment

logger = get_logger(__name__)


class IngestionResult:
    """Résultat d'une ingestion réussie."""

    def __init__(
        self,
        message: Message,
        conversation: Conversation,
        customer: Customer | None,
        is_new_conversation: bool,
        is_new_customer: bool,
    ) -> None:
        self.message = message
        self.conversation = conversation
        self.customer = customer
        self.is_new_conversation = is_new_conversation
        self.is_new_customer = is_new_customer


class MessageIngestionService:
    """Service central d'ingestion des messages.

    Tous les connecteurs passent par ce service pour insérer
    des messages dans Jenny. Il garantit la déduplication,
    la résolution client et la création de conversations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.message_repo = MessageRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.conversation_repo = ConversationRepository(session)
        self.event_repo = MessageEventRepository(session)

    async def ingest(self, message_in: MessageIn) -> IngestionResult:
        """Ingère un message canonique dans Jenny.

        Args:
            message_in: Payload canonique produit par un connecteur.

        Returns:
            IngestionResult avec le message, la conversation et le client.

        Raises:
            ValidationError: Si le message est un doublon.
        """
        # ── 1. Déduplication ──
        is_duplicate = await self.message_repo.exists_by_external_id(
            business_id=message_in.business_id,
            channel=message_in.channel,
            external_message_id=message_in.external_message_id,
        )
        if is_duplicate:
            logger.info(
                "ingestion.duplicate",
                external_id=message_in.external_message_id,
                channel=message_in.channel,
            )
            raise ValidationError(f"Message déjà ingéré : {message_in.external_message_id}")

        # ── 2. Résolution / création du client ──
        customer, is_new_customer = await self._resolve_or_create_customer(message_in)

        # ── 3. Résolution / création de la conversation ──
        conversation, is_new_conversation = await self._resolve_or_create_conversation(
            message_in, customer
        )

        # ── 4. Persistance du message ──
        message = await self._persist_message(message_in, conversation, customer)

        # ── 5. Mise à jour de la conversation ──
        if not is_new_conversation:
            await self.conversation_repo.update_on_new_message(
                conversation_id=conversation.id,
                preview=message_in.content_text,
                timestamp=message_in.received_at,
            )

        # ── 5bis. Sentiment du message client (flag « mécontent » + auto-escalade) ──
        if message_in.direction == "inbound":
            sentiment = analyze_sentiment(message_in.content_text)
            conversation.sentiment = sentiment
            if sentiment == "negative":
                tags = list(conversation.tags or [])
                if "mécontent" not in tags:
                    tags.append("mécontent")
                    conversation.tags = tags
                # Auto-escalade (#5) : à la 1re bascule en négatif d'une
                # conversation non escaladée, on lève le drapeau, on remonte la
                # priorité et on notifie l'équipe pour une prise en charge rapide.
                if not conversation.is_escalated:
                    conversation.is_escalated = True
                    if conversation.priority_level in (None, "low", "medium"):
                        conversation.priority_level = "high"
                    self.session.add(
                        Notification(
                            business_id=conversation.business_id,
                            recipient=None,  # diffusion à toute l'équipe
                            kind="escalated",
                            title="Client mécontent à prendre en charge",
                            body=(message_in.content_text or "")[:160],
                            conversation_id=conversation.id,
                            meta={"reason": "negative_sentiment"},
                        )
                    )
            await self.session.flush()

        # ── 6. Log événement d'ingestion ──
        await self.event_repo.log_event(
            message_id=message.id,
            event_type="ingested",
            detail=f"Ingéré depuis {message_in.channel}",
            payload={"external_id": message_in.external_message_id},
        )

        logger.info(
            "ingestion.success",
            message_id=str(message.id),
            conversation_id=str(conversation.id),
            channel=message_in.channel,
            is_new_customer=is_new_customer,
            is_new_conversation=is_new_conversation,
        )

        return IngestionResult(
            message=message,
            conversation=conversation,
            customer=customer,
            is_new_conversation=is_new_conversation,
            is_new_customer=is_new_customer,
        )

    async def _resolve_or_create_customer(
        self, message_in: MessageIn
    ) -> tuple[Customer | None, bool]:
        """Résout un client existant ou en crée un nouveau.

        Priorité de résolution : email > phone > handle.
        Si aucun identifiant n'est fourni, retourne None.
        """
        # Rien à résoudre si pas d'identifiant
        if not any(
            [
                message_in.sender_email,
                message_in.sender_phone,
                message_in.sender_handle,
            ]
        ):
            return None, False

        # Tenter de trouver un client existant
        customer = await self.customer_repo.resolve_customer(
            business_id=message_in.business_id,
            email=message_in.sender_email,
            phone=message_in.sender_phone,
            handle=message_in.sender_handle,
        )

        if customer:
            # Mettre à jour last_seen_at
            customer.last_seen_at = datetime.now(UTC)
            await self.session.flush()
            return customer, False

        # Créer un nouveau client
        now = datetime.now(UTC)
        customer = await self.customer_repo.create(
            business_id=message_in.business_id,
            full_name=message_in.sender_name,
            email=message_in.sender_email,
            phone=message_in.sender_phone,
            instagram_handle=message_in.sender_handle,
            first_seen_at=now,
            last_seen_at=now,
        )
        logger.info(
            "ingestion.customer_created",
            customer_id=str(customer.id),
            business_id=str(message_in.business_id),
        )
        return customer, True

    async def _resolve_or_create_conversation(
        self,
        message_in: MessageIn,
        customer: Customer | None,
    ) -> tuple[Conversation, bool]:
        """Résout une conversation existante ou en crée une nouvelle.

        Stratégie :
        1. Si external_conversation_id fourni → chercher par ID externe.
        2. Si client résolu → chercher une conversation ouverte sur ce canal.
        3. Sinon → créer une nouvelle conversation.
        """
        conversation: Conversation | None = None

        # 1. Par ID externe
        if message_in.external_conversation_id:
            conversation = await self.conversation_repo.find_by_external_id(
                business_id=message_in.business_id,
                channel=message_in.channel,
                external_conversation_id=message_in.external_conversation_id,
            )

        # 2. Par client + canal (conversation ouverte)
        if not conversation and customer:
            conversation = await self.conversation_repo.find_open_for_customer(
                business_id=message_in.business_id,
                customer_id=customer.id,
                channel=message_in.channel,
            )

        if conversation:
            return conversation, False

        # 3. Créer une nouvelle conversation
        preview = message_in.content_text[:200]
        conversation = await self.conversation_repo.create(
            business_id=message_in.business_id,
            customer_id=customer.id if customer else None,
            channel=message_in.channel,
            external_conversation_id=message_in.external_conversation_id,
            status="open",
            priority_level="medium",
            first_message_at=message_in.received_at,
            last_message_at=message_in.received_at,
            last_message_preview=preview,
            message_count=1,
        )
        logger.info(
            "ingestion.conversation_created",
            conversation_id=str(conversation.id),
        )
        return conversation, True

    async def _persist_message(
        self,
        message_in: MessageIn,
        conversation: Conversation,
        customer: Customer | None,
    ) -> Message:
        """Persiste le message en DB."""
        return await self.message_repo.create(
            conversation_id=conversation.id,
            business_id=message_in.business_id,
            customer_id=customer.id if customer else None,
            external_message_id=message_in.external_message_id,
            channel=message_in.channel,
            direction=message_in.direction,
            sender_name=message_in.sender_name,
            sender_email=message_in.sender_email,
            sender_phone=message_in.sender_phone,
            sender_handle=message_in.sender_handle,
            subject=message_in.subject,
            content_text=message_in.content_text,
            content_html=message_in.content_html,
            language=message_in.language,
            has_attachments=len(message_in.attachments) > 0,
            attachment_count=len(message_in.attachments),
            attachments_meta=message_in.attachments if message_in.attachments else None,
            status="received",
            source_created_at=message_in.source_created_at,
            received_at=message_in.received_at,
            raw_metadata=message_in.metadata if message_in.metadata else None,
        )
