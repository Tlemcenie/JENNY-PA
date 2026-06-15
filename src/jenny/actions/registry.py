"""Registre d'actions — Catalogue les actions disponibles.

Gère l'enregistrement et la résolution des actions
en fonction de l'intention détectée.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jenny.core.logging import get_logger

if TYPE_CHECKING:
    from jenny.actions.base import BaseAction

logger = get_logger(__name__)


class ActionRegistry:
    """Registre centralisé des actions disponibles.

    Permet d'enregistrer des actions et de les résoudre
    par intention ou par nom.
    """

    def __init__(self) -> None:
        self._actions_by_name: dict[str, BaseAction] = {}
        self._actions_by_intent: dict[str, BaseAction] = {}

    def register(
        self,
        action: BaseAction,
        intents: list[str] | None = None,
    ) -> None:
        """Enregistre une action.

        Args:
            action: Action à enregistrer.
            intents: Intentions qui déclenchent cette action.
        """
        self._actions_by_name[action.name] = action

        if intents:
            for intent in intents:
                self._actions_by_intent[intent] = action

        logger.info(
            "action_registry.register",
            action=action.name,
            intents=intents or [],
        )

    def get_action(self, intent_or_name: str) -> BaseAction | None:
        """Résout une action par intention ou par nom.

        Args:
            intent_or_name: Intention ou nom de l'action.

        Returns:
            L'action correspondante ou None.
        """
        # Chercher d'abord par intention
        action = self._actions_by_intent.get(intent_or_name)
        if action is not None:
            return action

        # Puis par nom
        return self._actions_by_name.get(intent_or_name)

    def list_actions(self) -> list[dict[str, str]]:
        """Liste toutes les actions enregistrées."""
        return [
            {
                "name": action.name,
                "description": action.description,
                "required_params": action.required_params,
            }
            for action in self._actions_by_name.values()
        ]
