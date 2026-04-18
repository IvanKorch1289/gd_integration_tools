"""Core interfaces — ABCs for infrastructure abstractions.

Позволяют подменять реализации (Redis→Memcached, S3→Azure, Kafka→NATS)
без изменения бизнес-логики.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


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


# ────────────────── Cache Backend ──────────────────


class CacheBackend(ABC):
    """Абстракция кэш-бэкенда (Redis, Memcached, in-memory)."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None: ...

    @abstractmethod
    async def delete(self, *keys: str) -> None: ...

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...


# ────────────────── Message Broker ──────────────────


class MessageBroker(ABC):
    """Абстракция message broker (Kafka, RabbitMQ, Redis Streams, NATS)."""

    @abstractmethod
    async def publish(self, topic: str, message: bytes, headers: dict[str, str] | None = None) -> None: ...

    @abstractmethod
    async def subscribe(self, topic: str, group: str | None = None) -> Any: ...

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...


# ────────────────── Object Storage ──────────────────


class ObjectStorage(ABC):
    """Абстракция объектного хранилища (S3, Azure Blob, GCS, MinIO)."""

    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]: ...

    @abstractmethod
    async def presigned_url(self, key: str, expires_in: int = 3600) -> str: ...


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
    """Lightweight circuit breaker для защиты от каскадных сбоев."""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        import time

        self.name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            import time
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
        import time
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

    async def __aexit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        if exc_val is None:
            self.record_success()
        else:
            self.record_failure()


class CircuitBreakerOpenError(Exception):
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
