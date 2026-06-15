"""Tests pour les schémas Pydantic."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jenny.domain.schemas.message import MessageCreate, MessageIn, MessageResponse


class TestMessageCreate:
    """Tests pour le schéma MessageCreate (legacy)."""

    def test_valid_message(self) -> None:
        msg = MessageCreate(
            channel="whatsapp",
            sender="+33612345678",
            content="Bonjour, je voudrais un devis.",
        )
        assert msg.channel == "whatsapp"
        assert msg.sender == "+33612345678"

    def test_invalid_channel(self) -> None:
        with pytest.raises(ValidationError):
            MessageCreate(
                channel="tiktok",  # type: ignore[arg-type]
                sender="user",
                content="Hello",
            )

    def test_empty_content(self) -> None:
        with pytest.raises(ValidationError):
            MessageCreate(
                channel="email",
                sender="user@example.com",
                content="",
            )


class TestMessageIn:
    """Tests pour le schéma canonique MessageIn."""

    def test_valid_message_in(self) -> None:
        msg = MessageIn(
            external_message_id="form:test:2026-03-10",
            channel="form",
            business_id=uuid4(),
            content_text="Bonjour, je voudrais un devis.",
            source_created_at=datetime.now(UTC),
            received_at=datetime.now(UTC),
        )
        assert msg.channel == "form"
        assert msg.direction == "inbound"

    def test_invalid_channel(self) -> None:
        with pytest.raises(ValidationError):
            MessageIn(
                external_message_id="test",
                channel="tiktok",  # type: ignore[arg-type]
                business_id=uuid4(),
                content_text="Hello",
                source_created_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )

    def test_empty_content_text(self) -> None:
        with pytest.raises(ValidationError):
            MessageIn(
                external_message_id="test",
                channel="email",
                business_id=uuid4(),
                content_text="",
                source_created_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )

    def test_optional_fields_default_to_none(self) -> None:
        msg = MessageIn(
            external_message_id="test",
            channel="whatsapp",
            business_id=uuid4(),
            content_text="Hello",
            source_created_at=datetime.now(UTC),
            received_at=datetime.now(UTC),
        )
        assert msg.sender_name is None
        assert msg.sender_email is None
        assert msg.sender_phone is None
        assert msg.subject is None
        assert msg.external_conversation_id is None


class TestMessageResponse:
    """Tests pour le schéma MessageResponse."""

    def test_defaults(self) -> None:
        resp = MessageResponse(
            id="123",
            channel="instagram",
            content="Hello",
        )
        assert resp.status == "received"
        assert resp.direction == "inbound"
        assert resp.priority is None
        assert resp.category is None
