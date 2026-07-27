"""Health checks для всех зарегистрированных коннекторов (S202 audit fix).

S202 audit: предыдущая версия содержала 9 broken references — неправильные
имена классов/методов или пропущенные ``await``. Текущая версия использует
реальные API клиентов и корректные signatures.

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
    """Kafka liveness check.

    S202: ``infrastructure.messaging.kafka_producer`` module doesn't exist
    (Kafka uses pool registration через ``kafka_pool_registration``).
    Проверяем registered pool в ``UnifiedPoolManager`` если доступен.
    """
    try:
        from src.backend.infrastructure.clients.unified_pool_manager import (
            get_unified_pool_manager,
        )

        manager = get_unified_pool_manager()
        return "kafka_main" in manager.list_pools()
    except Exception as exc:
        _logger.debug("check_kafka failed: %s", exc)
        return False


# ─────────────────────── MongoDB ─────────────────────────


async def check_mongodb() -> bool:
    """MongoDB liveness check через ping.

    S202 fix: добавлен ``await`` (раньше возвращал coroutine — always-truthy).
    """
    try:
        from src.backend.infrastructure.clients.storage.mongodb import MongoDBClient

        client = MongoDBClient()
        return await client.ping()
    except Exception as exc:
        _logger.debug("check_mongodb failed: %s", exc)
        return False


# ─────────────────────── ClickHouse ────────────────────────


async def check_clickhouse() -> bool:
    """ClickHouse liveness check через /ping.

    S202 fix: добавлен ``await``.
    """
    try:
        from src.backend.infrastructure.clients.storage.clickhouse import (
            get_clickhouse_client,
        )

        client = get_clickhouse_client()
        return await client.ping()
    except Exception as exc:
        _logger.debug("check_clickhouse failed: %s", exc)
        return False


# ───────────────────── Elasticsearch ──────────────────────


async def check_elasticsearch() -> bool:
    """Elasticsearch liveness check.

    S202 fix: добавлен ``await``.
    """
    try:
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )

        client = get_elasticsearch_client()
        return await client.ping()
    except Exception as exc:
        _logger.debug("check_elasticsearch failed: %s", exc)
        return False


# ─────────────────────────── NATS ──────────────────────────


async def check_nats() -> bool:
    """NATS liveness check.

    S202 fix: правильное имя класса ``NatsConnectionPool`` (не ``NATSPool``)
    и правильный method ``health()`` (не ``is_connected()``).
    """
    try:
        from src.backend.infrastructure.clients.transport.nats_pool import (
            NatsConnectionPool,
        )

        pool = NatsConnectionPool()
        result = await pool.health()
        return getattr(result, "status", None) != "failed"
    except Exception as exc:
        _logger.debug("check_nats failed: %s", exc)
        return False


# ────────────────────── Vector stores ──────────────────────


async def check_qdrant() -> bool:
    """Qdrant liveness check.

    S202 fix: правильное имя класса ``QdrantVectorStore`` (не
    ``VectorStoreClient``). ``count()`` — lightweight probe (vs full query).
    """
    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            QdrantVectorStore,
        )

        client = QdrantVectorStore()
        await client.count()
        return True
    except Exception as exc:
        _logger.debug("check_qdrant failed: %s", exc)
        return False


# ─────────────────────── EventBus ────────────────────────


async def check_eventbus() -> bool:
    """EventBus liveness check.

    S202 fix: правильный method ``health_check()`` (не ``is_available()``).
    """
    try:
        from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

        bus = get_event_bus()
        result = await bus.health_check()
        return isinstance(result, dict) and result.get("status") != "failed"
    except Exception as exc:
        _logger.debug("check_eventbus failed: %s", exc)
        return False


# ──────────────────────── HTTP ───────────────────────────


async def check_http() -> bool:
    """HTTP transport liveness check.

    S202 fix: ``HttpxClient`` имеет ``_ensure_client()`` (private). Используем
    presence check — singleton instance и async client construction.
    """
    try:
        from src.backend.infrastructure.clients.transport.http_httpx import (
            get_httpx_client,
        )

        client = get_httpx_client()
        await client._ensure_client()  # type: ignore[attr-defined]
        return True
    except Exception as exc:
        _logger.debug("check_http failed: %s", exc)
        return False


# ──────────────────────── Workflow ──────────────────────────


async def check_workflow() -> bool:
    """Workflow backend liveness check.

    S202 fix: workflow backends не имеют ``is_available()``. Проверяем
    backend instance presence + ``is_connected``-like attribute fallback.
    """
    try:
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        backend = await create_workflow_backend()
        # Backends не имеют единого is_available — проверяем базовое
        # наличие instance + опциональные атрибуты.
        if backend is None:
            return False
        # Некоторые backends (Temporal) имеют ``is_connected``
        if hasattr(backend, "is_connected"):
            return bool(backend.is_connected)
        # Fake / Lite — без remote connection, presence check достаточен.
        return True
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
