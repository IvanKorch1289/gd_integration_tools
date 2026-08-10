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

Sprint 173 M2.4: backward-compat re-exports для
``CircuitBreakerConfig`` / ``CircuitState`` / ``CircuitBreaker`` /
``CircuitBreakerOpenError`` реализованы через module-level
``__getattr__`` (lazy import), чтобы разорвать circular chain:
``core.interfaces.__init__`` → ``core.resilience.breaker`` →
``core.logging`` → ``infrastructure.logging.factory`` →
``core.interfaces.log_sink`` → ``core.interfaces.__init__``.
"""

from __future__ import annotations as annotations

from abc import ABC as ABC
from abc import abstractmethod as abstractmethod
from dataclasses import dataclass as dataclass
from enum import Enum as Enum
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult  # noqa: F401 — re-export
from src.backend.core.interfaces.audit import AuditBackend, AuditRecord  # noqa: F401 — re-export
from src.backend.core.interfaces.cache import CacheBackend  # noqa: F401 — re-export
from src.backend.core.interfaces.doc_store import DocStoreBackend  # noqa: F401 — re-export
from src.backend.core.interfaces.metrics import MetricsBackend  # noqa: F401 — re-export
from src.backend.core.interfaces.notification import (
    NotificationAdapter,
    NotificationMessage,
)
from src.backend.core.interfaces.secrets import SecretsBackend  # noqa: F401 — re-export
from src.backend.core.interfaces.storage import ObjectStorage  # noqa: F401 — re-export
from src.backend.core.logging import get_logger as get_logger

logger = get_logger(__name__)

# Sprint 173 M2.4: backward-compat re-exports — lazy через __getattr__,
# чтобы разорвать circular import (см. docstring).
# Eager import этих имён ломает collection: breaker.py импортирует
# core.logging, что триггерит infrastructure.logging.factory → … →
# core.interfaces.log_sink → core.interfaces.__init__ → (back here).
_CIRCUIT_BREAKER_REEXPORTS = (
    "CircuitBreakerConfig",
    "CircuitState",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
)

if TYPE_CHECKING:
    from src.backend.core.resilience.breaker import BreakerSpec as CircuitBreakerConfig
    from src.backend.core.resilience.breaker import BreakerState as CircuitState
    from src.backend.core.resilience.breaker import CircuitBreaker  # noqa: F401 — re-export
    from src.backend.core.resilience.breaker import (
        CircuitOpen as CircuitBreakerOpenError,
    )


def __getattr__(name: str) -> Any:
    """Lazy re-export для backward-compat CB-имён.

    Args:
        name: Имя атрибута модуля.

    Returns:
        Resolved symbol из ``core.resilience.breaker`` если name в
        :data:`_CIRCUIT_BREAKER_REEXPORTS`, иначе raise AttributeError.

    Notes:
        Используется вместо eager ``from ... import ...`` чтобы
        разорвать circular import chain при collection.

    """
    if name in _CIRCUIT_BREAKER_REEXPORTS:
        from src.backend.core.resilience.breaker import (
            BreakerSpec as CircuitBreakerConfig,
        )
        from src.backend.core.resilience.breaker import BreakerState as CircuitState
        from src.backend.core.resilience.breaker import CircuitBreaker  # noqa: F401 — re-export
        from src.backend.core.resilience.breaker import (
            CircuitOpen as CircuitBreakerOpenError,
        )

        mapping = {
            "CircuitBreakerConfig": CircuitBreakerConfig,
            "CircuitState": CircuitState,
            "CircuitBreaker": CircuitBreaker,
            "CircuitBreakerOpenError": CircuitBreakerOpenError,
        }
        value = mapping[name]
        globals()[name] = value  # cache for next access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = (
    "AntivirusBackend",
    "AntivirusScanResult",
    # Batching
    "AsyncBatcher",
    # Lifecycle
    "AsyncLifecycle",
    # Wave 21.3c fallback contracts
    "AuditBackend",
    "AuditRecord",
    # Auth
    "AuthProvider",
    # Cache / Storage / Antivirus / Notification (через подмодули)
    "CacheBackend",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    # Circuit breaker
    "CircuitState",
    "DocStoreBackend",
    "HealthReport",
    # Health
    "HealthStatus",
    "Healthcheck",
    "ManagedResource",
    # Messaging
    "MessageBroker",
    "MetricsBackend",
    "NotificationAdapter",
    "NotificationMessage",
    "ObjectStorage",
    # Pool
    "PoolMetrics",
    "PoolMetricsCollector",
    "SecretsBackend",
    "pool_metrics",
)


# ────────────────── Health Check ──────────────────


class HealthStatus(Enum):
    """Статус health check компонента.

    - HEALTHY: компонент полностью работоспособен
    - DEGRADED: компонент работает с ограничениями
    - UNHEALTHY: компонент неработоспособен
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class HealthReport:
    """Результат health check для конкретного компонента.

    Attributes:
        name: Имя компонента.
        status: Текущий статус.
        latency_ms: Задержка проверки в миллисекундах.
        details: Дополнительная информация (версия, метрики).

    """

    name: str
    status: HealthStatus
    latency_ms: float | None = None
    details: dict[str, Any] | None = None


class Healthcheck(ABC):
    """Любой компонент, поддерживающий health check."""

    @abstractmethod
    async def check_health(self) -> HealthReport:
        """Вернуть snapshot текущего health-state компонента."""
        ...


# ────────────────── Message Broker ──────────────────


class MessageBroker(ABC):
    """Абстракция message broker (Kafka, RabbitMQ, Redis Streams, NATS)."""

    @abstractmethod
    async def publish(
        self, topic: str, message: bytes, headers: dict[str, str] | None = None,
    ) -> None:
        """Опубликовать ``message`` в ``topic`` с опциональными headers."""
        ...

    @abstractmethod
    async def subscribe(self, topic: str, group: str | None = None) -> Any:
        """Подписаться на ``topic``; ``group`` — consumer group (None = broadcast)."""
        ...

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None:
        """Подтвердить обработку сообщения ``message_id`` (at-least-once)."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Установить соединение с broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Закрыть соединение с broker (graceful shutdown)."""
        ...


# ────────────────── Lifecycle ──────────────────


class AsyncLifecycle(ABC):
    """Компонент с async lifecycle (start/stop)."""

    @abstractmethod
    async def start(self) -> None:
        """Запустить компонент (idempotent)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Остановить компонент (graceful shutdown)."""
        ...


class ManagedResource(AsyncLifecycle, Healthcheck):
    """Компонент с lifecycle + health check."""



# ────────────────── Connection Pool Metrics ──────────────────


@dataclass(slots=True)
class PoolMetrics:
    """Метрики connection pool.

    Attributes:
        name: Имя пула.
        active: Активные соединения.
        idle: Простаивающие соединения.
        max_size: Максимальный размер пула.
        waiters: Ожидающие запросов.
        created_total: Всего созданных соединений.
        errors_total: Всего ошибок.

    """

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
        """Зарегистрировать новый pool по ``name`` с capacity ``max_size`` (0 = unbounded)."""
        self._pools[name] = PoolMetrics(name=name, max_size=max_size)

    def update(self, name: str, **kwargs: Any) -> None:
        """Обновить метрики ``name`` (только атрибуты, существующие в PoolMetrics)."""
        if name in self._pools:
            for k, v in kwargs.items():
                if hasattr(self._pools[name], k):
                    setattr(self._pools[name], k, v)

    def get_all(self) -> list[PoolMetrics]:
        """Метод get_all (см. signature)."""
        return list(self._pools.values())

    def get(self, name: str) -> PoolMetrics | None:
        """Метод get (см. signature)."""
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
        self, flush_fn: Any, batch_size: int = 100, flush_interval_seconds: float = 5.0,
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
        """Добавить item в буфер; триггерит flush при достижении ``batch_size``."""
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
        """Запустить background flush-задачу (interval-based)."""
        from src.backend.core.utils.task_registry import get_task_registry

        self._running = True
        self._task = get_task_registry().create_task(
            self._periodic_flush(), name="async-batcher-flush",
        )

    async def stop(self) -> None:
        """Остановить background flush и дождаться последнего батча."""
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
