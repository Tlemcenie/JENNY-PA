"""Tests unitaires pour le système d'actions."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jenny.actions.handlers.book_appointment import BookAppointmentAction
from jenny.actions.handlers.create_ticket import CreateTicketAction
from jenny.actions.handlers.order_check import CheckOrderAction
from jenny.actions.registry import ActionRegistry
from jenny.db.repositories.order_repo import OrderRepository
from jenny.db.repositories.support_ticket_repo import SupportTicketRepository


class TestActionRegistry:
    """Tests pour le registre d'actions."""

    def test_register_and_get_by_name(self) -> None:
        """Enregistre et retrouve une action par nom."""
        registry = ActionRegistry()
        action = CheckOrderAction()
        registry.register(action)

        found = registry.get_action("check_order")
        assert found is not None
        assert found.name == "check_order"

    def test_register_and_get_by_intent(self) -> None:
        """Enregistre et retrouve une action par intention."""
        registry = ActionRegistry()
        action = CheckOrderAction()
        registry.register(action, intents=["order_status"])

        found = registry.get_action("order_status")
        assert found is not None
        assert found.name == "check_order"

    def test_get_unknown_action(self) -> None:
        """Action non trouvée → None."""
        registry = ActionRegistry()
        assert registry.get_action("unknown") is None

    def test_list_actions(self) -> None:
        """Liste toutes les actions."""
        registry = ActionRegistry()
        registry.register(CheckOrderAction())
        registry.register(CreateTicketAction())

        actions = registry.list_actions()
        assert len(actions) == 2


class TestCheckOrderAction:
    """Tests pour l'action de vérification de commande."""

    @pytest.mark.asyncio
    async def test_check_order_success(self) -> None:
        """Vérifie une commande avec succès."""
        bid = str(uuid.uuid4())
        fake_order = MagicMock()
        fake_order.reference = "CMD-12345"
        fake_order.status = "en_cours_livraison"
        fake_order.total_amount_minor = 10000
        fake_order.currency = "EUR"

        with patch.object(
            OrderRepository,
            "get_by_reference",
            new_callable=AsyncMock,
            return_value=fake_order,
        ):
            action = CheckOrderAction()
            result = await action.execute({"order_number": "CMD-12345", "business_id": bid})

        assert result["success"] is True
        assert "CMD-12345" in result["message"]
        assert result["data"]["status"] == "en_cours_livraison"

    @pytest.mark.asyncio
    async def test_check_order_missing_param(self) -> None:
        """Manque le numéro de commande."""
        action = CheckOrderAction()
        result = await action.execute({})

        assert result["success"] is False

    def test_validate_params(self) -> None:
        """Valide les paramètres requis."""
        action = CheckOrderAction()
        missing = action.validate_params({})
        assert "order_number" in missing

        missing = action.validate_params({"order_number": "CMD-123"})
        assert len(missing) == 0


class TestCreateTicketAction:
    """Tests pour la création de ticket."""

    @pytest.mark.asyncio
    async def test_create_ticket(self) -> None:
        """Crée un ticket avec succès."""
        bid = str(uuid.uuid4())
        tid = uuid.uuid4()
        fake = MagicMock()
        fake.id = tid
        fake.reference = "TKT-42"
        fake.status = "open"

        with patch.object(
            SupportTicketRepository,
            "create_ticket",
            new_callable=AsyncMock,
            return_value=fake,
        ):
            action = CreateTicketAction()
            result = await action.execute({"email": "test@example.com", "business_id": bid})

        assert result["success"] is True
        assert result["data"]["reference"].startswith("TKT")


class TestBookAppointmentAction:
    """Tests pour la réservation de rendez-vous."""

    @pytest.mark.asyncio
    async def test_book_appointment(self) -> None:
        """Réserve un rendez-vous."""
        action = BookAppointmentAction()
        result = await action.execute({"date": "20/03/2026"})

        assert result["success"] is True
        assert "confirmé" in result["message"]

    @pytest.mark.asyncio
    async def test_book_appointment_missing_date(self) -> None:
        """Manque la date."""
        action = BookAppointmentAction()
        result = await action.execute({})

        assert result["success"] is False
