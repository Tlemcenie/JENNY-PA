"""Interface abstraite pour les connecteurs de messagerie.

Chaque canal (WhatsApp, Instagram, Messenger, email, formulaire)
implémentera cette interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawMessage:
    """Message brut reçu d'un connecteur externe."""

    external_id: str
    channel: str
    sender: str
    content: str
    raw_payload: dict  # Payload original du canal
    timestamp: str | None = None


class BaseConnector(ABC):
    """Interface commune pour tous les connecteurs de messagerie."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Nom du canal (ex: 'whatsapp', 'instagram')."""
        ...

    @abstractmethod
    async def fetch_messages(self) -> list[RawMessage]:
        """Récupère les nouveaux messages depuis le canal.

        Returns:
            Liste de messages bruts normalisés.
        """
        ...

    @abstractmethod
    async def send_reply(self, external_id: str, content: str) -> bool:
        """Envoie une réponse sur le canal.

        Args:
            external_id: ID du message original côté canal.
            content: Contenu de la réponse.

        Returns:
            True si l'envoi a réussi.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Vérifie la connectivité avec le canal externe."""
        ...
