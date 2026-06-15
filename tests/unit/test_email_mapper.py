"""Tests pour le mapper email → MessageIn."""

from datetime import UTC, datetime
from uuid import uuid4

from jenny.connectors.email.mapper import map_email_to_message_in
from jenny.connectors.email.schema import EmailAttachment, EmailPayload


class TestEmailMapper:
    """Tests du mapper email → MessageIn canonique."""

    def _make_payload(self, **overrides) -> EmailPayload:  # type: ignore[no-untyped-def]
        """Helper pour créer un payload de test."""
        defaults = {
            "message_id": "<abc123@mail.example.com>",
            "from_email": "client@example.com",
            "from_name": "Jean Martin",
            "to_email": "contact@monbusiness.fr",
            "subject": "Question sur vos tarifs",
            "text_body": "Bonjour, pourriez-vous me communiquer vos tarifs ?",
            "sent_at": datetime(2026, 3, 10, 15, 0, 0, tzinfo=UTC),
        }
        defaults.update(overrides)
        return EmailPayload(**defaults)

    def test_basic_mapping(self) -> None:
        """Le mapper produit un MessageIn valide."""
        business_id = uuid4()
        payload = self._make_payload()

        result = map_email_to_message_in(payload, business_id)

        assert result.channel == "email"
        assert result.direction == "inbound"
        assert result.business_id == business_id
        assert result.sender_name == "Jean Martin"
        assert result.sender_email == "client@example.com"
        assert result.subject == "Question sur vos tarifs"
        assert result.content_text == "Bonjour, pourriez-vous me communiquer vos tarifs ?"

    def test_external_message_id_is_email_message_id(self) -> None:
        """L'ID externe est le Message-ID de l'email."""
        payload = self._make_payload()
        result = map_email_to_message_in(payload, uuid4())

        assert result.external_message_id == "<abc123@mail.example.com>"

    def test_thread_id_used_for_conversation(self) -> None:
        """Si thread_id est fourni, il sert d'external_conversation_id."""
        payload = self._make_payload(thread_id="thread-xyz")
        result = map_email_to_message_in(payload, uuid4())

        assert result.external_conversation_id == "thread-xyz"

    def test_in_reply_to_used_for_conversation_fallback(self) -> None:
        """Si pas de thread_id, in_reply_to sert de fallback."""
        payload = self._make_payload(
            thread_id=None,
            in_reply_to="<parent@mail.example.com>",
        )
        result = map_email_to_message_in(payload, uuid4())

        assert result.external_conversation_id == "<parent@mail.example.com>"

    def test_message_id_as_conversation_last_resort(self) -> None:
        """Sans thread_id ni in_reply_to, le message_id est utilisé."""
        payload = self._make_payload(thread_id=None, in_reply_to=None)
        result = map_email_to_message_in(payload, uuid4())

        assert result.external_conversation_id == "<abc123@mail.example.com>"

    def test_attachments_are_normalized(self) -> None:
        """Les pièces jointes sont correctement normalisées."""
        attachments = [
            EmailAttachment(
                filename="devis.pdf",
                content_type="application/pdf",
                size_bytes=12345,
                url="https://s3.example.com/devis.pdf",
            )
        ]
        payload = self._make_payload(attachments=attachments)
        result = map_email_to_message_in(payload, uuid4())

        assert len(result.attachments) == 1
        assert result.attachments[0]["filename"] == "devis.pdf"
        assert result.attachments[0]["size_bytes"] == 12345
