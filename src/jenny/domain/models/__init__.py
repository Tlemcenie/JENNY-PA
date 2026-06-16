"""Modèles SQLAlchemy du domaine Jenny.

Importer tous les modèles ici pour que l'autogenerate Alembic
puisse les découvrir automatiquement.
"""

from jenny.domain.models.api_key import ApiKey
from jenny.domain.models.appointment import Appointment
from jenny.domain.models.audit_log import AuditLog
from jenny.domain.models.business import Business
from jenny.domain.models.business_closure import BusinessClosure
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.canned_response import CannedResponse
from jenny.domain.models.channel_account import ChannelAccount
from jenny.domain.models.conversation import Conversation
from jenny.domain.models.customer import Customer
from jenny.domain.models.customer_address import CustomerAddress
from jenny.domain.models.customer_document import CustomerDocument
from jenny.domain.models.customer_fact import CustomerFact
from jenny.domain.models.customer_transaction import CustomerTransaction
from jenny.domain.models.document_category import DocumentCategory
from jenny.domain.models.knowledge_gap import KnowledgeGap
from jenny.domain.models.message import Message
from jenny.domain.models.message_event import MessageEvent
from jenny.domain.models.notification import Notification
from jenny.domain.models.order import Order
from jenny.domain.models.payment_record import PaymentRecord
from jenny.domain.models.pending_question import PendingQuestion
from jenny.domain.models.prestation import Prestation
from jenny.domain.models.quote import Quote
from jenny.domain.models.review import Review
from jenny.domain.models.support_ticket import SupportTicket
from jenny.domain.models.transaction_type import TransactionType
from jenny.domain.models.user import User
from jenny.domain.models.waitlist_entry import WaitlistEntry
from jenny.domain.models.webhook_delivery import WebhookDelivery

__all__ = [
    "ApiKey",
    "Appointment",
    "AuditLog",
    "Business",
    "BusinessClosure",
    "BusinessMember",
    "CannedResponse",
    "ChannelAccount",
    "Conversation",
    "Customer",
    "CustomerAddress",
    "CustomerDocument",
    "CustomerFact",
    "CustomerTransaction",
    "DocumentCategory",
    "KnowledgeGap",
    "Message",
    "MessageEvent",
    "Notification",
    "Order",
    "PaymentRecord",
    "PendingQuestion",
    "Prestation",
    "Quote",
    "Review",
    "SupportTicket",
    "TransactionType",
    "User",
    "WaitlistEntry",
    "WebhookDelivery",
]
