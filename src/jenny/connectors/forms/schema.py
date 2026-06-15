"""Schéma du payload entrant pour les formulaires.

Définit la structure attendue quand un formulaire de contact
(Google Forms, Typeform, formulaire custom) envoie une soumission.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class FormSubmissionPayload(BaseModel):
    """Payload brut d'une soumission de formulaire.

    Ce schéma est le contrat d'entrée pour le webhook /ingest/form.
    Il sera transformé en MessageIn canonique par le mapper.
    """

    form_id: str = Field(..., description="ID du formulaire source")
    submitted_at: datetime = Field(..., description="Timestamp de soumission")
    full_name: str | None = Field(default=None, description="Nom complet du contact")
    email: EmailStr | None = Field(default=None, description="Email du contact")
    phone: str | None = Field(default=None, max_length=50, description="Téléphone du contact")
    subject: str | None = Field(default=None, max_length=500, description="Sujet du message")
    message: str = Field(..., min_length=1, description="Contenu du message")
    page_url: str | None = Field(default=None, description="URL de la page contenant le formulaire")
    metadata: dict = Field(
        default_factory=dict,
        description="Données additionnelles du formulaire",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "form_id": "contact-main",
                    "submitted_at": "2026-03-10T14:30:00Z",
                    "full_name": "Marie Dupont",
                    "email": "marie@example.com",
                    "phone": "+33612345678",
                    "subject": "Demande de devis",
                    "message": "Bonjour, je voudrais un devis pour une prestation photo.",
                    "page_url": "https://monsite.fr/contact",
                }
            ]
        }
    }
