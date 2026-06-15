"""Instrumentation OpenTelemetry optionnelle (OTLP HTTP si configuré)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def instrument_fastapi_if_configured(app: FastAPI) -> None:
    """Active l'export OTLP HTTP si ``OTEL_EXPORTER_OTLP_ENDPOINT`` est defini.

    Dependances optionnelles : ``pip install opentelemetry-instrumentation-fastapi
    opentelemetry-exporter-otlp-proto-http``.
    """
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "jenny")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
