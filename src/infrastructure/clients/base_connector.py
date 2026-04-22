"""Connector SPI — единый интерфейс для всех infrastructure-клиентов.

Соответствует ADR-022 и плану IL1 (см. `/root/.claude/plans/tidy-jingling-map.md`
и `docs/phases/PHASE_IL1.md`).

Коммерческий референс — MuleSoft `ConnectionProvider<T>`, Apache Camel
`Component`+`Endpoint`, WSO2 `AbstractConnector`.

Каждый infra-клиент (Postgres / Redis / Mongo / Kafka / RabbitMQ / SMTP / IMAP
/ S3 / httpx / gRPC / SOAP) наследует `InfrastructureClient` ABC и предоставляет
единый lifecycle: ``start / stop / health / validate / reload``. Это позволяет
ConnectorRegistry (см. `src/infrastructure/registry.py`) централизованно
управлять всем слоем.

Существующие клиенты мигрируются постепенно; shim на старые import-path
сохраняется на один релиз (plan deletion в H3_PLUS).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config.pooling import DEFAULT_POOLING_PROFILE, PoolingProfile


HealthMode = Literal["fast", "deep"]
HealthStatus = Literal["ok", "degraded", "failed"]


@dataclass(slots=True)
class HealthResult:
    """Результат health-проверки клиента.

    * ``status`` — итоговое состояние; ``ok`` = всё в порядке, ``degraded`` =
      отвечает, но с предупреждениями (например, Postgres replica lag > N
      секунд), ``failed`` = связь недоступна.
    * ``latency_ms`` — время ответа в миллисекундах.
    * ``mode`` — с каким уровнем глубины проверяли (`fast` < 100ms, `deep` < 2s).
    * ``details`` — произвольные ключ-значения (например, `replica_lag_s`,
      `topic_count`, `queue_depth`).
    * ``error`` — краткое человекочитаемое описание, если `status != "ok"`.
    """

    status: HealthStatus
    latency_ms: float
    mode: HealthMode
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def ok(cls, *, latency_ms: float, mode: HealthMode, **details: Any) -> "HealthResult":
        return cls(status="ok", latency_ms=latency_ms, mode=mode, details=dict(details))

    @classmethod
    def failed(cls, *, error: str, mode: HealthMode, latency_ms: float = 0.0) -> "HealthResult":
        return cls(status="failed", latency_ms=latency_ms, mode=mode, error=error)

    @classmethod
    def degraded(
        cls, *, error: str, mode: HealthMode, latency_ms: float, **details: Any
    ) -> "HealthResult":
        return cls(
            status="degraded",
            latency_ms=latency_ms,
            mode=mode,
            error=error,
            details=dict(details),
        )


class InfrastructureClient(ABC):
    """Базовый абстрактный класс для всех infra-клиентов.

    Каждый клиент обязан реализовать ``start``/``stop``/``health``.
    ``validate`` и ``reload`` реализованы по умолчанию через эти три метода;
    клиент может переопределить их для оптимизаций (например, Postgres
    может делать ``SET SESSION`` reload без закрытия pool).

    Именование: ``name`` должно быть уникальным в рамках процесса — оно
    используется как Prometheus label и ключ в `ConnectorRegistry`.
    """

    #: Уникальное имя клиента (label в Prometheus, ключ в Registry).
    name: str

    #: Pool-параметры — `PoolingProfile`. Если клиент не использует пул,
    #: передаётся `DEFAULT_POOLING_PROFILE` (несколько полей всё равно
    #: применяются — например, circuit_threshold / circuit_recovery_s).
    pooling: PoolingProfile

    def __init__(self, *, name: str, pooling: PoolingProfile | None = None) -> None:
        self.name = name
        self.pooling = pooling or DEFAULT_POOLING_PROFILE
        self._started: bool = False

    # -- Lifecycle -----------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Инициализация: открытие соединений / поднятие pool-а.

        Должен быть идемпотентен: повторный вызов после successful start —
        no-op (проверка через ``self._started``).
        """

    @abstractmethod
    async def stop(self) -> None:
        """Graceful shutdown: drain in-flight + close connections.

        Должен быть безопасен при повторе (после stop может не быть ресурсов).
        """

    @abstractmethod
    async def health(self, mode: HealthMode = "fast") -> HealthResult:
        """Health-проверка.

        ``fast`` (default) — быстрый PING, SLA < 100ms. Используется в
        Kubernetes liveness probe.

        ``deep`` — smoke-operation (Postgres ``SELECT pg_is_in_recovery()``,
        Kafka ``list_topics()``, и т.д.), SLA < 2s. Используется в readiness
        probe и on-demand dashboard.
        """

    async def validate(self) -> None:
        """Периодическая проверка из scheduler'а (default — раз в минуту).

        Default-реализация — `health(mode="fast")`; при `failed` бросает
        исключение, чтобы registry мог зафиксировать и перевести клиент в
        degraded. Клиент может переопределить для более дешёвого ping'а.
        """
        result = await self.health(mode="fast")
        if result.status == "failed":
            raise ConnectorValidationError(
                f"Validation failed for connector '{self.name}': {result.error}"
            )

    async def reload(self) -> None:
        """Atomic reload: drain → rebuild → swap → close.

        Default-реализация — `stop()` + `start()`. Клиент может переопределить
        для более умного rebuild (например, пересоздание pool-а без потери
        in-flight запросов — использовать seconds grace).
        """
        await self.stop()
        await self.start()

    # -- Helpers -------------------------------------------------------

    async def _timed_health(
        self, probe: "callable[[], Any]", mode: HealthMode
    ) -> HealthResult:
        """Helper для клиентов: оборачивает probe-колбек в timing + exception handling."""
        start = time.perf_counter()
        try:
            extra = await probe() if callable(probe) else {}
            latency_ms = (time.perf_counter() - start) * 1000.0
            details = extra if isinstance(extra, dict) else {}
            return HealthResult.ok(latency_ms=latency_ms, mode=mode, **details)
        except Exception as exc:  # noqa: BLE001  (хотим поймать всё)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}",
                mode=mode,
                latency_ms=latency_ms,
            )


class ConnectorValidationError(RuntimeError):
    """Исключение, которое бросает `validate()` при failed health."""


__all__ = (
    "HealthMode",
    "HealthResult",
    "HealthStatus",
    "InfrastructureClient",
    "ConnectorValidationError",
)
