"""Единый набор Prometheus client-side метрик для infra-клиентов.

RED-стандарт (Rate / Errors / Duration) + pool-saturation + circuit state.
Все метрики имеют одинаковый label-set, что позволяет строить
cross-client-дашборды и alerts одним запросом.

Соответствует ADR-022 и плану IL1.2 (см.
`/root/.claude/plans/tidy-jingling-map.md`).

Lables:
  * ``client`` — имя клиента (как в ConnectorRegistry), например `redis` / `postgres`.
  * ``operation`` — конкретная операция, например `SET` / `GET` / `SELECT`.
  * ``outcome`` — `success` / `error` / `timeout` / `circuit_open`.
  * ``tenant`` — tenant_id из TenantContext; `_system` если отсутствует.

Клиенты интегрируются через `ClientMetricsMixin` или вручную через
контекст-менеджер `track_operation(...)`.

Коммерческий референс — MuleSoft Anypoint Monitoring metrics namespace;
TIBCO EMS per-topic statistics.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Final, Literal

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    pass


_logger = logging.getLogger(__name__)


Outcome = Literal["success", "error", "timeout", "circuit_open"]
PoolState = Literal["active", "idle", "waiting", "max"]
CircuitState = Literal["closed", "open", "half_open"]
DegradationLabel = Literal["normal", "degraded", "down"]


#: Бакеты Histogram — покрывают диапазон от 10ms до 10s, подходят для
#: большинства client-side-операций. Более агрессивные (<1ms) не нужны, т.к.
#: client_metrics — это wire-time, а не CPU-time.
_LATENCY_BUCKETS: Final = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_LABELS: Final = ("client", "operation", "outcome", "tenant")
_POOL_LABELS: Final = ("client", "state")
_CIRCUIT_LABELS: Final = ("client", "host")
_DEGRADATION_LABELS: Final = ("component",)


# --- Ядро метрик -----------------------------------------------------

requests_total: Final = Counter(
    "infra_client_requests_total",
    "Total number of infra-client operations (RED: Rate).",
    labelnames=_LABELS,
)

request_duration_seconds: Final = Histogram(
    "infra_client_request_duration_seconds",
    "Duration of infra-client operations in seconds (RED: Duration).",
    labelnames=_LABELS,
    buckets=_LATENCY_BUCKETS,
)

pool_size: Final = Gauge(
    "infra_client_pool_size",
    "Current size of infra-client connection pool by state.",
    labelnames=_POOL_LABELS,
)

circuit_state: Final = Gauge(
    "infra_client_circuit_state",
    "Circuit breaker state: 0=closed, 1=open, 2=half_open.",
    labelnames=_CIRCUIT_LABELS,
)

degradation_mode: Final = Gauge(
    "app_degradation_mode",
    (
        "Component-level degradation indicator (W26 ResilienceCoordinator): "
        "0=normal, 1=degraded (fallback active), 2=down (all backends "
        "exhausted)."
    ),
    labelnames=_DEGRADATION_LABELS,
)


_CIRCUIT_VALUES: Final[dict[CircuitState, int]] = {
    "closed": 0,
    "open": 1,
    "half_open": 2,
}

_DEGRADATION_VALUES: Final[dict[DegradationLabel, int]] = {
    "normal": 0,
    "degraded": 1,
    "down": 2,
}


# --- Helpers ---------------------------------------------------------


def _current_tenant() -> str:
    """Получить tenant_id из ContextVar; `_system` если не задан."""
    try:
        # Поздний импорт, чтобы не создавать цикл.
        from src.core.tenancy import current_tenant  # type: ignore[attr-defined]

        tenant = current_tenant()
        if tenant is None:
            return "_system"
        # Может быть object или str — берём tenant_id.
        return getattr(tenant, "tenant_id", None) or str(tenant) or "_system"
    except Exception:  # noqa: BLE001
        return "_system"


def record_request(
    *,
    client: str,
    operation: str,
    outcome: Outcome,
    duration_s: float,
    tenant: str | None = None,
) -> None:
    """Ручная запись события в метрики.

    Используется, если клиент не может применить context-manager
    `track_operation` (например, callback-based API).
    """
    t = tenant or _current_tenant()
    labels = {"client": client, "operation": operation, "outcome": outcome, "tenant": t}
    requests_total.labels(**labels).inc()
    request_duration_seconds.labels(**labels).observe(duration_s)


def record_pool_state(
    *, client: str, active: int, idle: int, waiting: int, max_size: int
) -> None:
    """Записать текущее состояние pool-а. Обычно вызывается из validate()."""
    pool_size.labels(client=client, state="active").set(active)
    pool_size.labels(client=client, state="idle").set(idle)
    pool_size.labels(client=client, state="waiting").set(waiting)
    pool_size.labels(client=client, state="max").set(max_size)


def record_circuit_state(*, client: str, host: str, state: CircuitState) -> None:
    """Обновить gauge состояния circuit-breaker'а."""
    circuit_state.labels(client=client, host=host).set(_CIRCUIT_VALUES[state])


def record_degradation_mode(*, component: str, label: DegradationLabel) -> None:
    """Обновить gauge degradation-уровня компонента (W26).

    Источник — ``ResilienceCoordinator.degradation_mode(component)``;
    публикуется при каждом успешном/неуспешном вызове в pipeline'е и
    периодически из health-aggregator (см. W26.2).
    """
    degradation_mode.labels(component=component).set(_DEGRADATION_VALUES[label])


@asynccontextmanager
async def track_operation(
    *, client: str, operation: str, tenant: str | None = None
) -> AsyncIterator[None]:
    """Async context-manager для инструментации одной client-операции.

    Пример:

        async with track_operation(client="redis", operation="GET"):
            await redis.get(key)

    При исключении outcome автоматически ставится в `error`; для `timeout` и
    `circuit_open` используйте `record_request(...)` напрямую или
    соответствующие exception-типы (см. `TIMEOUT_EXCEPTIONS`).
    """
    start = time.perf_counter()
    try:
        yield
        record_request(
            client=client,
            operation=operation,
            outcome="success",
            duration_s=time.perf_counter() - start,
            tenant=tenant,
        )
    except _TIMEOUT_EXC_TYPES as exc:
        record_request(
            client=client,
            operation=operation,
            outcome="timeout",
            duration_s=time.perf_counter() - start,
            tenant=tenant,
        )
        raise exc
    except _CIRCUIT_OPEN_EXC_TYPES as exc:
        record_request(
            client=client,
            operation=operation,
            outcome="circuit_open",
            duration_s=time.perf_counter() - start,
            tenant=tenant,
        )
        raise exc
    except Exception as exc:  # noqa: BLE001
        record_request(
            client=client,
            operation=operation,
            outcome="error",
            duration_s=time.perf_counter() - start,
            tenant=tenant,
        )
        raise exc


# Поздняя резолюция типов исключений: purgatory.OpenedState, asyncio.TimeoutError.
def _resolve_exception_types() -> tuple[
    tuple[type[BaseException], ...], tuple[type[BaseException], ...]
]:
    import asyncio

    timeout_types: list[type[BaseException]] = [asyncio.TimeoutError, TimeoutError]
    circuit_types: list[type[BaseException]] = []
    try:
        from purgatory.domain.model import OpenedState

        circuit_types.append(OpenedState)
    except ImportError:
        pass
    return tuple(timeout_types), tuple(circuit_types)


_TIMEOUT_EXC_TYPES, _CIRCUIT_OPEN_EXC_TYPES = _resolve_exception_types()

# Экспортируем для клиентов, которые хотят ручной проброс.
TIMEOUT_EXCEPTIONS: Final = _TIMEOUT_EXC_TYPES
CIRCUIT_OPEN_EXCEPTIONS: Final = _CIRCUIT_OPEN_EXC_TYPES


# --- Mixin для InfrastructureClient ----------------------------------


class ClientMetricsMixin:
    """Добавляет self.track(operation) к `InfrastructureClient`-у.

    Использование:

        class RedisConnector(ClientMetricsMixin, InfrastructureClient):
            async def get(self, key):
                async with self.track("GET"):
                    return await self._redis.get(key)

    Mixin идёт **слева** от ABC, чтобы MRO взял `track` из него (ABC не
    обязывает реализацию).
    """

    name: str  # type: ignore[no-untyped-def]  (поставляется ABC)

    def track(
        self, operation: str, *, tenant: str | None = None
    ) -> "AsyncIterator[None]":
        """Shortcut для `track_operation(client=self.name, ...)`."""
        return track_operation(client=self.name, operation=operation, tenant=tenant)

    def report_pool(self, *, active: int, idle: int, waiting: int) -> None:
        """Обновить gauge-метрики pool-а. Обычно вызывается из validate()."""
        # type: ignore[no-untyped-def]  (self.pooling из ABC)
        max_size = (
            getattr(self, "pooling", None).max_size
            if getattr(self, "pooling", None)
            else 0
        )  # type: ignore[union-attr]
        record_pool_state(
            client=self.name,
            active=active,
            idle=idle,
            waiting=waiting,
            max_size=max_size,
        )

    def report_circuit(self, *, host: str, state: CircuitState) -> None:
        """Обновить gauge circuit-state."""
        record_circuit_state(client=self.name, host=host, state=state)


__all__ = (
    "CircuitState",
    "ClientMetricsMixin",
    "DegradationLabel",
    "Outcome",
    "PoolState",
    "circuit_state",
    "degradation_mode",
    "pool_size",
    "record_circuit_state",
    "record_degradation_mode",
    "record_pool_state",
    "record_request",
    "request_duration_seconds",
    "requests_total",
    "track_operation",
    "TIMEOUT_EXCEPTIONS",
    "CIRCUIT_OPEN_EXCEPTIONS",
)
