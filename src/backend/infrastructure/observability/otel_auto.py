"""OpenTelemetry auto-instrumentation.

Автоматически инструментирует FastAPI / HTTPX / SQLAlchemy / asyncpg /
Redis / Logging / aiokafka / aio-pika / PyMongo (Motor) / gRPC client
без ручных spans в коде.

Активируется в main.py::
    from src.backend.infrastructure.observability.otel_auto import init_otel
    init_otel(app=fastapi_app)

Требует env OTEL_EXPORTER_OTLP_ENDPOINT (иначе skip).

IL1.3 (ADR-022): добавлены Kafka / RabbitMQ / MongoDB / gRPC-client
instrumentations — закрывает observability-gap в infra-слое.

Sprint 1 V16: добавлен asyncpg instrumentor (detail-level db spans
поверх SQLAlchemy spans, raw asyncpg-вызовы вне ORM).
"""

from __future__ import annotations

import logging
import os
from typing import Any

__all__ = ("init_otel", "instrument_asyncpg_if_enabled")

logger = logging.getLogger("infra.otel")

# Guard — защита от двойного вызова instrument_asyncpg_if_enabled()
_ASYNCPG_INSTRUMENTED: bool = False


def instrument_asyncpg_if_enabled() -> bool:
    """Инструментирует asyncpg через OTel под управлением feature-flag ``otel_asyncpg``.

    Вызывается однократно при создании asyncpg-engine. Защищён guard-флагом
    ``_ASYNCPG_INSTRUMENTED`` от повторного вызова. Fail-safe: если пакет
    ``opentelemetry-instrumentation-asyncpg`` не установлен или feature-flag
    отключён — возвращает ``False`` без исключений.

    Returns:
        True если AsyncPGInstrumentor().instrument() был вызван в этом запуске,
        False если flag OFF или пакет недоступен.
    """
    global _ASYNCPG_INSTRUMENTED
    if _ASYNCPG_INSTRUMENTED:
        logger.debug(
            "OTel asyncpg instrumentor уже активирован, пропуск повторного вызова"
        )
        return False

    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.otel_asyncpg:
            logger.debug("feature_flag.otel_asyncpg=False — asyncpg OTel пропущен")
            return False
    except Exception as exc:
        logger.debug("Не удалось прочитать feature_flags: %s", exc)
        return False

    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
        _ASYNCPG_INSTRUMENTED = True
        logger.info("OTel asyncpg instrumented via feature_flag.otel_asyncpg")
        return True
    except ImportError as exc:
        logger.debug("opentelemetry-instrumentation-asyncpg недоступен: %s", exc)
        return False


def init_otel(*, app: Any = None, service_name: str | None = None) -> bool:
    """Инициализирует OpenTelemetry с auto-instrumentation.

    Инструментирует:
    - FastAPI (HTTP server spans)
    - httpx (HTTP client spans)
    - SQLAlchemy (DB query spans)
    - asyncpg (raw asyncpg detail-level spans) — Sprint 1 V16
    - Redis (command spans)
    - Logging (trace_id/span_id в log records)
    - aiokafka (Kafka produce/consume spans) — IL1.3
    - aio-pika (RabbitMQ publish/consume spans) — IL1.3
    - PyMongo через Motor (MongoDB ops spans) — IL1.3
    - gRPC client (unary/stream spans) — IL1.3

    Новые instrumentations fail gracefully при отсутствующем пакете —
    logger.debug с причиной, без исключений.

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
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry SDK not installed: %s", exc)
        return False

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": environment}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    _instrument_fastapi(app)
    _instrument_httpx()
    _instrument_sqlalchemy()
    _instrument_redis()
    _instrument_logging()
    # IL1.3: расширение coverage до messaging / mongo / grpc-client.
    _instrument_aiokafka()
    _instrument_aiopika()
    _instrument_pymongo()
    _instrument_grpc_client()
    # Sprint 1 V16: detail-level spans для raw asyncpg вне SQLAlchemy.
    _instrument_asyncpg()

    logger.info(
        "OpenTelemetry initialized: service=%s, env=%s", service_name, environment
    )
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


def _instrument_aiokafka() -> None:
    """Kafka producer/consumer spans. Требует
    opentelemetry-instrumentation-aiokafka.
    """
    try:
        from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor

        AIOKafkaInstrumentor().instrument()
        logger.debug("OTel aiokafka instrumented")
    except ImportError as exc:
        logger.debug("OTel aiokafka instrumentor skipped: %s", exc)


def _instrument_aiopika() -> None:
    """RabbitMQ publish/consume spans. Требует
    opentelemetry-instrumentation-aio-pika.
    """
    try:
        from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

        AioPikaInstrumentor().instrument()
        logger.debug("OTel aio-pika instrumented")
    except ImportError as exc:
        logger.debug("OTel aio-pika instrumentor skipped: %s", exc)


def _instrument_pymongo() -> None:
    """PyMongo / Motor spans.

    Motor использует PyMongo под капотом, поэтому PyMongoInstrumentor
    охватывает и async operations. Требует
    opentelemetry-instrumentation-pymongo.
    """
    try:
        from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

        PymongoInstrumentor().instrument()
        logger.debug("OTel pymongo instrumented")
    except ImportError as exc:
        logger.debug("OTel pymongo instrumentor skipped: %s", exc)


def _instrument_grpc_client() -> None:
    """gRPC client-side spans (unary + streaming).

    Server-side уже инструментируется отдельно при старте gRPC server-а.
    Требует opentelemetry-instrumentation-grpc.
    """
    try:
        from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient

        GrpcAioInstrumentorClient().instrument()
        logger.debug("OTel gRPC async client instrumented")
    except ImportError as exc:
        logger.debug("OTel gRPC client instrumentor skipped: %s", exc)


def _instrument_asyncpg() -> None:
    """asyncpg raw-driver spans.

    SQLAlchemy spans покрывают ORM-уровень; asyncpg instrumentation
    добавляет detail-level spans с ``db.statement`` атрибутами для
    raw asyncpg.Connection.execute / fetch / executemany — полезно
    для diff'ов между low-level и ORM-путями. Требует
    opentelemetry-instrumentation-asyncpg.
    """
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
        logger.debug("OTel asyncpg instrumented")
    except ImportError as exc:
        logger.debug("OTel asyncpg instrumentor skipped: %s", exc)
