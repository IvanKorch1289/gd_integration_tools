"""Протоколы для observability-компонентов.

Wave 6.2: вынесено из `infrastructure/application/...`, чтобы services-слой
мог зависеть только от ABC/Protocol, не нарушая layer policy
(services → core, schemas).

Реализации остаются в `infrastructure/application/`:
* :class:`SLOTracker` (slo_tracker.py)
* :class:`HealthAggregator` (health_aggregator.py)
* :class:`HealthCheck` (monitoring/health_check.py)

Все Protocol помечены ``@runtime_checkable`` для поддержки isinstance-проверок
в тестах.
"""

from __future__ import annotations

from typing import Any, AsyncContextManager, Protocol, runtime_checkable

__all__ = (
    "SLOTrackerProtocol",
    "HealthAggregatorProtocol",
    "HealthCheckProtocol",
    "HealthCheckSessionProtocol",
)


@runtime_checkable
class SLOTrackerProtocol(Protocol):
    """Контракт SLO-трекера: метрики P50/P95/P99 на маршрут.

    Реализация: ``infrastructure.application.slo_tracker.SLOTracker``.
    """

    def record(
        self, route_id: str, latency_ms: float, is_error: bool = False
    ) -> None:
        """Регистрирует latency-измерение для маршрута."""
        ...

    def get_report(self) -> dict[str, Any]:
        """Возвращает агрегированный SLO-отчёт по всем маршрутам."""
        ...

    def get_route_stats(self, route_id: str) -> dict[str, Any]:
        """Возвращает статистику по конкретному маршруту."""
        ...

    def reset(self) -> None:
        """Сбрасывает накопленную статистику."""
        ...


@runtime_checkable
class HealthAggregatorProtocol(Protocol):
    """Контракт агрегатора health-checks.

    Реализация: ``infrastructure.application.health_aggregator.HealthAggregator``.
    """

    async def check_all(self, *, mode: str = "fast") -> dict[str, Any]:
        """Параллельно опрашивает все зарегистрированные health-checks."""
        ...

    async def check_single(self, name: str, *, mode: str = "fast") -> dict[str, Any]:
        """Опрашивает один зарегистрированный компонент."""
        ...


@runtime_checkable
class HealthCheckSessionProtocol(Protocol):
    """Контракт session-объекта healthcheck (то, что возвращает context manager).

    Реализация: ``infrastructure.monitoring.health_check.HealthCheck``.
    """

    async def check_database(self) -> bool: ...
    async def check_redis(self) -> bool: ...
    async def check_s3(self) -> bool: ...
    async def check_s3_bucket(self) -> bool: ...
    async def check_graylog(self) -> bool: ...
    async def check_smtp(self) -> bool: ...
    async def check_rabbitmq(self) -> bool: ...
    async def check_all_services(self) -> dict[str, Any]: ...


@runtime_checkable
class HealthCheckProtocol(Protocol):
    """Контракт фабрики healthcheck-сессий (async context manager).

    Реализация: ``infrastructure.monitoring.health_check.get_healthcheck_service``
    (асинхронный generator оборачивается в asynccontextmanager).
    """

    def __call__(self) -> AsyncContextManager[HealthCheckSessionProtocol]:
        """Возвращает async context manager для healthcheck-сессии."""
        ...
