"""Core interfaces — ABC-контракты для инфраструктурных абстракций.

Wave 1.1: монолитный ``core/interfaces.py`` разбит на тематические модули:

* :mod:`core.interfaces.cache` — :class:`CacheBackend` (Redis / KeyDB / Memcached / Memory).
* :mod:`core.interfaces.storage` — :class:`ObjectStorage` (S3 / Azure / GCS / LocalFS).
* :mod:`core.interfaces.antivirus` — :class:`AntivirusBackend` (ClamAV / HTTP).
* :mod:`core.interfaces.notification` — :class:`NotificationAdapter` (Email / Express / ...).

Прочие ABC (Healthcheck, MessageBroker, AsyncLifecycle,
PoolMetrics, AuthProvider, AsyncBatcher) остаются в этом файле — они
плотно связаны и переезд в отдельные модули не уменьшает зацепления.

CircuitBreaker вынесен в ``core.resilience.breaker`` (canonical, purgatory backend).

Публичный API сохранён: ``from src.backend.core.interfaces import X`` продолжает
работать для всех ранее экспортируемых имён.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult
from src.backend.core.interfaces.audit import AuditBackend, AuditRecord
from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.interfaces.doc_store import DocStoreBackend
from src.backend.core.interfaces.metrics import MetricsBackend
from src.backend.core.interfaces.notification import (
    NotificationAdapter,
    NotificationMessage,
)
from src.backend.core.interfaces.secrets import SecretsBackend
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger

# Backward compat (sibling W3 moved CircuitBreaker to core.resilience.breaker
# but kept CircuitBreaker as alias; extend with aliases for the OTHER
# renamed names so existing test imports like
# `from src.backend.core.interfaces import CircuitBreakerConfig` still work):
from src.backend.core.resilience.breaker import (  # noqa: E402
    BreakerSpec as CircuitBreakerConfig,
)
from src.backend.core.resilience.breaker import BreakerState as CircuitState
from src.backend.core.resilience.breaker import (
    CircuitBreaker,  # already aliased in breaker.__init__ for backward compat
)
from src.backend.core.resilience.breaker import CircuitOpen as CircuitBreakerOpenError

logger = get_logger(__name__)

__all__ = (
    # Health
    "HealthStatus",
    "HealthReport",
    "Healthcheck",
    # Cache / Storage / Antivirus / Notification (через подмодули)
    "CacheBackend",
    "ObjectStorage",
    "AntivirusBackend",
    "AntivirusScanResult",
    "NotificationAdapter",
    "NotificationMessage",
    # Wave 21.3c fallback contracts
    "AuditBackend",
    "AuditRecord",
    "DocStoreBackend",
    "SecretsBackend",
    "MetricsBackend",
    # Messaging
    "MessageBroker",
    # Lifecycle
    "AsyncLifecycle",
    "ManagedResource",
    # Circuit breaker
    "CircuitState",
    "CircuitBreakerConfig",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    # Pool
    "PoolMetrics",
    "PoolMetricsCollector",
    "pool_metrics",
    # Auth
    "AuthProvider",
    # Batching
    "AsyncBatcher",
)


# ────────────────── Health Check ──────────────────


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class HealthReport:
    name: str
    status: HealthStatus
    latency_ms: float | None = None
    details: dict[str, Any] | None = None


class Healthcheck(ABC):
    """Любой компонент, поддерживающий health check."""

    @abstractmethod
    async def check_health(self) -> HealthReport: ...


# ────────────────── Message Broker ──────────────────


class MessageBroker(ABC):
    """Абстракция message broker (Kafka, RabbitMQ, Redis Streams, NATS)."""

    @abstractmethod
    async def publish(
        self, topic: str, message: bytes, headers: dict[str, str] | None = None
    ) -> None: ...

    @abstractmethod
    async def subscribe(self, topic: str, group: str | None = None) -> Any: ...

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...


# ────────────────── Lifecycle ──────────────────


class AsyncLifecycle(ABC):
    """Компонент с async lifecycle (start/stop)."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


class ManagedResource(AsyncLifecycle, Healthcheck):
    """Компонент с lifecycle + health check."""

    pass


# ────────────────── Connection Pool Metrics ──────────────────


@dataclass(slots=True)
class PoolMetrics:
    name: str
    active: int = 0
    idle: int = 0
    max_size: int = 0
    waiters: int = 0
    created_total: int = 0
    errors_total: int = 0


class PoolMetricsCollector:
    """Сбор метрик connection pool-ов."""

    def __init__(self) -> None:
        self._pools: dict[str, PoolMetrics] = {}

    def register(self, name: str, max_size: int = 0) -> None:
        self._pools[name] = PoolMetrics(name=name, max_size=max_size)

    def update(self, name: str, **kwargs: Any) -> None:
        if name in self._pools:
            for k, v in kwargs.items():
                if hasattr(self._pools[name], k):
                    setattr(self._pools[name], k, v)

    def get_all(self) -> list[PoolMetrics]:
        return list(self._pools.values())

    def get(self, name: str) -> PoolMetrics | None:
        return self._pools.get(name)


pool_metrics = PoolMetricsCollector()


# ────────────────── Auth Provider ──────────────────


class AuthProvider(ABC):
    """Pluggable authentication provider (LDAP, OAuth2, JWT, API Key)."""

    name: str = "base"

    @abstractmethod
    async def authenticate(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Аутентификация. Возвращает user info или None."""
        ...

    @abstractmethod
    async def authorize(self, user: dict[str, Any], resource: str, action: str) -> bool:
        """Авторизация: может ли user выполнить action на resource."""
        ...


# ────────────────── Async Batcher ──────────────────


class AsyncBatcher:
    """Generic async batcher — накапливает items, flush по batch_size или interval."""

    def __init__(
        self, flush_fn: Any, batch_size: int = 100, flush_interval_seconds: float = 5.0
    ) -> None:
        import asyncio

        self._flush_fn = flush_fn
        self._batch_size = batch_size
        self._interval = flush_interval_seconds
        self._buffer: list[Any] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._running = False

    async def add(self, item: Any) -> None:
        async with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= self._batch_size:
                await self._do_flush()

    async def _do_flush(self) -> None:
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()
        try:
            result = self._flush_fn(batch)
            if hasattr(result, "__await__"):
                await result
        except Exception as _:
            logger.debug("AsyncBatcher flush_fn raised; batch dropped", exc_info=True)

    async def start(self) -> None:
        from src.backend.core.utils.task_registry import get_task_registry

        self._running = True
        self._task = get_task_registry().create_task(
            self._periodic_flush(), name="async-batcher-flush"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        async with self._lock:
            await self._do_flush()

    async def _periodic_flush(self) -> None:
        import asyncio

        while self._running:
            await asyncio.sleep(self._interval)
            async with self._lock:
                await self._do_flush()
