"""Core interfaces — ABC-контракты для инфраструктурных абстракций.

Wave 1.1: монолитный ``core/interfaces.py`` разбит на тематические модули:

* :mod:`core.interfaces.cache` — :class:`CacheBackend` (Redis / KeyDB / Memcached / Memory).
* :mod:`core.interfaces.storage` — :class:`ObjectStorage` (S3 / Azure / GCS / LocalFS).
* :mod:`core.interfaces.antivirus` — :class:`AntivirusBackend` (ClamAV / HTTP).
* :mod:`core.interfaces.notification` — :class:`NotificationAdapter` (Email / Express / ...).

Прочие ABC (Healthcheck, MessageBroker, AsyncLifecycle, CircuitBreaker,
PoolMetrics, AuthProvider, AsyncBatcher) остаются в этом файле — они
плотно связаны и переезд в отдельные модули не уменьшает зацепления.

Публичный API сохранён: ``from src.core.interfaces import X`` продолжает
работать для всех ранее экспортируемых имён.
"""

from __future__ import annotations

import time  # PERF-5: top-level import (hot path — CircuitBreaker state checks)
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult
from src.core.interfaces.cache import CacheBackend
from src.core.interfaces.notification import NotificationAdapter, NotificationMessage
from src.core.interfaces.storage import ObjectStorage

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


# ────────────────── Circuit Breaker ──────────────────


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    success_threshold: int = 2


class CircuitBreaker:
    """Lightweight circuit breaker — обёртка над :mod:`aiocircuitbreaker`.

    Сохраняет публичный API (``state``, ``record_success``, ``record_failure``,
    ``allow_request``, ``__aenter__/__aexit__``) для обратной совместимости
    с 11+ callsite'ами. Внутри использует батл-тестед реализацию из
    ``aiocircuitbreaker`` (если установлена); иначе — минимальный fallback.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name
        self._config = config or CircuitBreakerConfig()
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._state = CircuitState.CLOSED

        try:
            from aiocircuitbreaker import CircuitBreaker as _AioCB

            self._aio = _AioCB(
                failure_threshold=self._config.failure_threshold,
                recovery_timeout=self._config.recovery_timeout,
                name=name,
            )
        except ImportError:
            self._aio = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            return self._half_open_calls <= self._config.half_open_max_calls
        return False

    async def __aenter__(self) -> "CircuitBreaker":
        if not self.allow_request():
            raise CircuitBreakerOpenError(self.name)
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        if exc_val is None:
            self.record_success()
        else:
            self.record_failure()


class CircuitBreakerOpenError(Exception):
    """Исключение при попытке вызова через открытый CB."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit breaker '{name}' is OPEN")
        self.breaker_name = name


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
    async def authorize(
        self, user: dict[str, Any], resource: str, action: str
    ) -> bool:
        """Авторизация: может ли user выполнить action на resource."""
        ...


# ────────────────── Async Batcher ──────────────────


class AsyncBatcher:
    """Generic async batcher — накапливает items, flush по batch_size или interval."""

    def __init__(
        self,
        flush_fn: Any,
        batch_size: int = 100,
        flush_interval_seconds: float = 5.0,
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
        except Exception:
            pass

    async def start(self) -> None:
        import asyncio

        self._running = True
        self._task = asyncio.create_task(self._periodic_flush())

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
