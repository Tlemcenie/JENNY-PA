"""Pipeline de données.

Orchestre les étapes de traitement des données :
raw → interim → processed → labeled.
"""

from dataclasses import dataclass
from enum import StrEnum

from jenny.core.logging import get_logger

logger = get_logger(__name__)


class DataStage(StrEnum):
    """Étapes du pipeline de données."""

    RAW = "raw"
    INTERIM = "interim"
    PROCESSED = "processed"
    LABELED = "labeled"
    SYNTHETIC = "synthetic"


@dataclass
class PipelineResult:
    """Résultat d'exécution d'un pipeline."""

    stage: DataStage
    records_processed: int
    success: bool
    errors: list[str]


class DataPipeline:
    """Pipeline de traitement des données messages.

    Étapes :
    1. Extraction (depuis connecteurs / DB)
    2. Nettoyage et normalisation
    3. Enrichissement (features, metadata)
    4. Stockage dans le stage suivant

    TODO: implémenter chaque étape.
    """

    def __init__(self, source_stage: DataStage, target_stage: DataStage) -> None:
        self.source_stage = source_stage
        self.target_stage = target_stage

    async def run(self) -> PipelineResult:
        """Exécute le pipeline.

        TODO: implémenter la logique réelle de transformation.
        """
        logger.info(
            "pipeline.data.run",
            source=self.source_stage.value,
            target=self.target_stage.value,
        )
        # Placeholder
        return PipelineResult(
            stage=self.target_stage,
            records_processed=0,
            success=True,
            errors=[],
        )

    async def validate(self) -> bool:
        """Valide la qualité des données après transformation.

        TODO: checks de qualité (nulls, distributions, doublons...).
        """
        logger.info("pipeline.data.validate", stage=self.target_stage.value)
        return True
