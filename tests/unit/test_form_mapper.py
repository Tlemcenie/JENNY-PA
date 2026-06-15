"""Tests pour le mapper formulaire → MessageIn."""

from datetime import UTC, datetime
from uuid import uuid4

from jenny.connectors.forms.mapper import map_form_to_message_in
from jenny.connectors.forms.schema import FormSubmissionPayload


class TestFormMapper:
    """Tests du mapper formulaire → MessageIn canonique."""

    def _make_payload(self, **overrides) -> FormSubmissionPayload:  # type: ignore[no-untyped-def]
        """Helper pour créer un payload de test."""
        defaults = {
            "form_id": "contact-main",
            "submitted_at": datetime(2026, 3, 10, 14, 0, 0, tzinfo=UTC),
            "full_name": "Marie Dupont",
            "email": "marie@example.com",
            "phone": "+33612345678",
            "subject": "Demande de devis",
            "message": "Bonjour, je voudrais un devis.",
            "page_url": "https://monsite.fr/contact",
        }
        defaults.update(overrides)
        return FormSubmissionPayload(**defaults)

    def test_basic_mapping(self) -> None:
        """Le mapper produit un MessageIn valide avec les bons champs."""
        business_id = uuid4()
        payload = self._make_payload()

        result = map_form_to_message_in(payload, business_id)

        assert result.channel == "form"
        assert result.direction == "inbound"
        assert result.business_id == business_id
        assert result.sender_name == "Marie Dupont"
        assert result.sender_email == "marie@example.com"
        assert result.sender_phone == "+33612345678"
        assert result.content_text == "Bonjour, je voudrais un devis."
        assert result.subject == "Demande de devis"

    def test_external_message_id_format(self) -> None:
        """L'ID externe suit le format form:{form_id}:{timestamp}."""
        payload = self._make_payload()
        result = map_form_to_message_in(payload, uuid4())

        assert result.external_message_id.startswith("form:contact-main:")
        assert "2026-03-10" in result.external_message_id

    def test_no_external_conversation_id(self) -> None:
        """Les formulaires n'ont pas de notion de conversation externe."""
        payload = self._make_payload()
        result = map_form_to_message_in(payload, uuid4())

        assert result.external_conversation_id is None

    def test_metadata_contains_form_id_and_page_url(self) -> None:
        """La metadata contient le form_id et la page_url."""
        payload = self._make_payload()
        result = map_form_to_message_in(payload, uuid4())

        assert result.metadata["form_id"] == "contact-main"
        assert result.metadata["page_url"] == "https://monsite.fr/contact"

    def test_minimal_payload(self) -> None:
        """Un payload minimal (sans nom, email, phone) est valide."""
        payload = self._make_payload(
            full_name=None,
            email=None,
            phone=None,
            subject=None,
            page_url=None,
        )
        result = map_form_to_message_in(payload, uuid4())

        assert result.channel == "form"
        assert result.sender_name is None
        assert result.sender_email is None
        assert result.content_text == "Bonjour, je voudrais un devis."

    def test_received_at_is_set(self) -> None:
        """Le received_at est automatiquement rempli."""
        payload = self._make_payload()
        result = map_form_to_message_in(payload, uuid4())

        assert result.received_at is not None

    def test_source_created_at_matches_submitted_at(self) -> None:
        """Le source_created_at correspond au submitted_at du formulaire."""
        submitted = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        payload = self._make_payload(submitted_at=submitted)
        result = map_form_to_message_in(payload, uuid4())

        assert result.source_created_at == submitted

    def test_extra_metadata_is_preserved(self) -> None:
        """Les metadata additionnelles du formulaire sont conservées."""
        payload = self._make_payload(metadata={"utm_source": "google", "campaign": "spring2026"})
        result = map_form_to_message_in(payload, uuid4())

        assert result.metadata["utm_source"] == "google"
        assert result.metadata["campaign"] == "spring2026"
