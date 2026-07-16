"""Health checks для всех зарегистрированных коннекторов (Sprint I-2).

Расширяет покрытие с 7 (db, redis, s3, graylog, smtp, rabbitmq) до 15+:
- Kafka (admin client list_topics)
- MongoDB (ping)
- ClickHouse (HTTP /ping)
- Elasticsearch (cluster.health)
- NATS (connection.is_connected)
- Vector stores (Qdrant/Chroma)
- HTTP transport (sample HEAD request)
- EventBus (Redis ping)
- Workflow (Temporal availability)

Все checks — async callable возвращающие bool, ловят exceptions internally
для graceful degradation.

Использование::

    from src.backend.services.monitoring.checks import register_default_checks

    facade = get_health_facade()
    register_default_checks(facade)
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "check_clickhouse",
    "check_elasticsearch",
    "check_eventbus",
    "check_http",
    "check_kafka",
    "check_mongodb",
    "check_nats",
    "check_qdrant",
    "check_workflow",
    "register_default_checks",
)

_logger = get_logger("services.monitoring.checks")

HealthCheckFn = Callable[[], Coroutine[Any, Any, bool]]


# ───────────────────────── Kafka ─────────────────────────


async def check_kafka() -> bool:
    """Kafka liveness check через admin client.

    Returns:
        True если Kafka broker доступен, False иначе.
    """
    try:
        from src.backend.infrastructure.messaging.kafka_producer import (
            KafkaProducer,
        )

        producer = KafkaProducer()
        return producer.is_available()
    except Exception as exc:
        _logger.debug("check_kafka failed: %s", exc)
        return False


# ─────────────────────── MongoDB ─────────────────────────


async def check_mongodb() -> bool:
    """MongoDB liveness check через Motor ping.

    Returns:
        True если MongoDB отвечает на ping, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.storage.mongodb import (
            MongoDBClient,
        )

        client = MongoDBClient()
        return client.ping()
    except Exception as exc:
        _logger.debug("check_mongodb failed: %s", exc)
        return False


# ─────────────────────── ClickHouse ────────────────────────


async def check_clickhouse() -> bool:
    """ClickHouse liveness check через HTTP /ping.

    Returns:
        True если ClickHouse отвечает на /ping, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.storage.clickhouse import (
            get_clickhouse_client,
        )

        client = get_clickhouse_client()
        return client.ping()
    except Exception as exc:
        _logger.debug("check_clickhouse failed: %s", exc)
        return False


# ───────────────────── Elasticsearch ──────────────────────


async def check_elasticsearch() -> bool:
    """Elasticsearch liveness check через cluster.health.

    Returns:
        True если ES cluster healthy, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            ElasticsearchClient,
        )

        client = ElasticsearchClient()
        return client.ping()
    except Exception as exc:
        _logger.debug("check_elasticsearch failed: %s", exc)
        return False


# ─────────────────────────── NATS ──────────────────────────


async def check_nats() -> bool:
    """NATS liveness check через connection.is_connected.

    Returns:
        True если NATS connection активна, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.transport.nats_pool import (
            NATSPool,
        )

        pool = NATSPool()
        return pool.is_connected()
    except Exception as exc:
        _logger.debug("check_nats failed: %s", exc)
        return False


# ────────────────────── Vector stores ──────────────────────


async def check_qdrant() -> bool:
    """Qdrant liveness check.

    Returns:
        True если Qdrant отвечает, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            VectorStoreClient,
        )

        client = VectorStoreClient(backend="qdrant")
        return client.is_available()
    except Exception as exc:
        _logger.debug("check_qdrant failed: %s", exc)
        return False


# ─────────────────────── EventBus ────────────────────────


async def check_eventbus() -> bool:
    """EventBus liveness check (Redis backend).

    Returns:
        True если EventBus broker доступен, False иначе.
    """
    try:
        from src.backend.core.messaging.event_bus import get_event_bus

        bus = get_event_bus()
        return bus.is_available()
    except Exception as exc:
        _logger.debug("check_eventbus failed: %s", exc)
        return False


# ──────────────────────── HTTP ───────────────────────────


async def check_http() -> bool:
    """HTTP transport liveness check (sample HEAD request).

    Использует localhost health endpoint или upstream pool ping.
    Returns:
        True если HTTP client готов, False иначе.
    """
    try:
        from src.backend.infrastructure.clients.transport.http_httpx import (
            get_httpx_client,
        )

        client = get_httpx_client()
        return client.is_ready()
    except Exception as exc:
        _logger.debug("check_http failed: %s", exc)
        return False


# ──────────────────────── Workflow ──────────────────────────


async def check_workflow() -> bool:
    """Workflow backend (Temporal / Lite / PgRunner) liveness check.

    Returns:
        True если workflow backend доступен, False иначе.
    """
    try:
        from src.backend.infrastructure.workflow.factory import (
            get_workflow_backend,
        )

        backend = get_workflow_backend()
        return backend.is_available()
    except Exception as exc:
        _logger.debug("check_workflow failed: %s", exc)
        return False


# ─────────────────────── Registration ──────────────────────


DEFAULT_CHECKS: dict[str, HealthCheckFn] = {
    "kafka": check_kafka,
    "mongodb": check_mongodb,
    "clickhouse": check_clickhouse,
    "elasticsearch": check_elasticsearch,
    "nats": check_nats,
    "qdrant": check_qdrant,
    "eventbus": check_eventbus,
    "http": check_http,
    "workflow": check_workflow,
}


def register_default_checks(facade: Any) -> int:
    """Зарегистрировать default health checks в facade.

    Args:
        facade: HealthFacade instance.

    Returns:
        Число зарегистрированных checks.
    """
    registered = 0
    for name, check_fn in DEFAULT_CHECKS.items():
        try:
            facade.register_check(name, check_fn)
            registered += 1
        except Exception as exc:
            _logger.warning("Failed to register check %s: %s", name, exc)
    return registered
