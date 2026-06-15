"""Exceptions métier centralisées.

Toutes les exceptions spécifiques au domaine Jenny sont définies ici
pour un traitement cohérent dans les handlers FastAPI.
"""


class JennyError(Exception):
    """Exception de base pour toute erreur métier Jenny."""

    def __init__(self, message: str = "Une erreur est survenue") -> None:
        self.message = message
        super().__init__(self.message)


class NotFoundError(JennyError):
    """Ressource non trouvée."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} non trouvé(e) : {identifier}")
        self.resource = resource
        self.identifier = identifier


class ValidationError(JennyError):
    """Erreur de validation métier (distincte de Pydantic)."""


class ConnectorError(JennyError):
    """Erreur lors de la communication avec un connecteur externe."""

    def __init__(self, connector: str, detail: str) -> None:
        super().__init__(f"Erreur connecteur {connector} : {detail}")
        self.connector = connector


class LLMError(JennyError):
    """Erreur lors de l'appel à un fournisseur LLM."""


class PipelineError(JennyError):
    """Erreur dans un pipeline de données ou d'entraînement."""
