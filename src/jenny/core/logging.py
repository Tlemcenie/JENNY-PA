"""Configuration du logging structuré.

Utilise structlog pour un logging structuré, lisible en dev
et JSON-ready en production.
"""

import logging
import sys

import structlog

from jenny.core.config import get_settings


def setup_logging() -> None:
    """Configure le logging pour l'application.

    - Dev : rendu console coloré et lisible.
    - Prod : rendu JSON pour ingestion par des outils d'observabilité.
    """
    settings = get_settings()

    # Processors partagés
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.is_prod:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())

    # Réduire le bruit des loggers tiers
    for logger_name in ("uvicorn", "sqlalchemy.engine", "httpx"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Retourne un logger structuré nommé."""
    return structlog.get_logger(name)
