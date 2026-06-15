"""Interface de base pour les actions exécutables.

Chaque action convertit une demande client en opération
concrète : vérifier une commande, créer un ticket, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar


@dataclass
class ActionResult:
    """Résultat d'une action exécutée."""

    success: bool
    message: str
    data: dict = field(default_factory=dict)
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        """Convertit en dictionnaire."""
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class BaseAction(ABC):
    """Classe de base pour toutes les actions.

    Chaque action représente une opération métier concrète
    déclenchée par un agent suite à une demande client.
    """

    name: str = "base_action"
    description: str = ""
    required_params: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def execute(self, params: dict) -> dict:
        """Exécute l'action avec les paramètres fournis.

        Args:
            params: Paramètres extraits des slots (ex: {"order_number": "CMD-123"})

        Returns:
            Résultat de l'action sous forme de dictionnaire.
        """
        ...

    def validate_params(self, params: dict) -> list[str]:
        """Vérifie que tous les paramètres requis sont présents.

        Returns:
            Liste des paramètres manquants.
        """
        return [p for p in self.required_params if p not in params or not params[p]]
