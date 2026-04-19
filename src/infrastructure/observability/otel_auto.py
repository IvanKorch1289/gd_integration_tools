"""OpenTelemetry auto-instrumentation.

Автоматически инструментирует FastAPI / HTTPX / SQLAlchemy / Redis / Logging
без ручных spans в коде.

Активируется в main.py::
    from app.infrastructure.observability.otel_auto import init_otel
    init_otel(app=fastapi_app)

Требует env OTEL_EXPORTER_OTLP_ENDPOINT (иначе skip).
"""

from __future__ import annotations

import logging
import os
from typing import Any

__all__ = ("init_otel",)

logger = logging.getLogger("infra.otel")


def init_otel(*, app: Any = None, service_name: str | None = None) -> bool:
    """Инициализирует OpenTelemetry с auto-instrumentation.

    Инструментирует:
    - FastAPI (HTTP server spans)
    - httpx (HTTP client spans)
    - SQLAlchemy (DB query spans)
    - Redis (command spans)
    - Logging (trace_id/span_id в log records)

    Returns True если инициализировано.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping OTel init")
        return False

    service_name = service_name or os.environ.get("OTEL_SERVICE_NAME", "gd_integration")
    environment = os.environ.get("APP_ENVIRONMENT", "development")

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry SDK not installed: %s", exc)
        return False

    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": environment,
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    _instrument_fastapi(app)
    _instrument_httpx()
    _instrument_sqlalchemy()
    _instrument_redis()
    _instrument_logging()

    logger.info("OpenTelemetry initialized: service=%s, env=%s", service_name, environment)
    return True


def _instrument_fastapi(app: Any) -> None:
    if app is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("OTel FastAPI instrumented")
    except ImportError:
        pass


def _instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.debug("OTel httpx instrumented")
    except ImportError:
        pass


def _instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
        logger.debug("OTel SQLAlchemy instrumented")
    except ImportError:
        pass


def _instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.debug("OTel Redis instrumented")
    except ImportError:
        pass


def _instrument_logging() -> None:
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=True)
        logger.debug("OTel Logging instrumented")
    except ImportError:
        pass
