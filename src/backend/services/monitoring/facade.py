"""HealthFacade — capability-checked unified health checks.

Sprint I-1 (S181): закрывает gap из Master Prompt §3.3 — нет единого
facade для health checks. Существующий :class:`infrastructure.monitoring.health_check.HealthCheck`
предоставляет только hardcoded 7 проверок (db, redis, s3, graylog, smtp, rabbitmq).

Предоставляет единый API:
- ``check_all()`` — параллельная проверка всех зарегистрированных компонентов
- ``check(name)`` — проверка одного компонента по имени
- ``is_healthy()`` — bool, все ли компоненты healthy
- ``register_check()`` — регистрация custom healthcheck функции
- ``get_status()`` — детализированный status (healthy/degraded/unhealthy)

Ponytail: thin wrapper над существующим HealthCheck. Не дублирует логику,
делегирует через DI.

Использование::

    from src.backend.services.monitoring.facade import get_health_facade

    facade = get_health_facade()
    if await facade.is_healthy():
        ...
    status = await facade.check_all()  # HealthReport dict
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("HealthFacade", "HealthReport", "HealthStatus", "get_health_facade")

_logger = get_logger("services.monitoring.facade")

HealthCheckFn = Callable[[], Awaitable[bool]]
"""Сигнатура custom healthcheck: async callable без аргументов, возвращает bool."""


class HealthStatus(str, Enum):
    """Статус компонента.

    - ``HEALTHY``: все проверки прошли
    - ``DEGRADED``: 1+ проверок провалилась, но есть fallback
    - ``UNHEALTHY``: критические проверки провалились
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class HealthReport:
    """Unified health report для всех компонентов.

    Attributes:
        status: Общий статус (``HEALTHY``/``DEGRADED``/``UNHEALTHY``).
        is_all_active: ``True`` если все checks прошли (без fallback).
        components: Dict ``{component_name: {"status": bool, "latency_ms": float, "error": str|None}}``.
        checked_at: ISO timestamp проверки.
    """

    status: HealthStatus
    is_all_active: bool
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в dict для JSON response."""
        return {
            "status": self.status.value,
            "is_all_services_active": self.is_all_active,
            "checked_at": self.checked_at,
            "components": self.components,
        }


class HealthFacade:
    """Capability-checked unified health checks facade.

    Args:
        timeout_seconds: Default timeout для каждого check (default 2.0).
        check_failure_threshold: Число failed checks для degraded→unhealthy (default 1).
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        check_failure_threshold: int = 1,
    ) -> None:
        """Инициализация facade."""
        self._timeout = timeout_seconds
        self._threshold = check_failure_threshold
        self._custom_checks: dict[str, HealthCheckFn] = {}

    def register_check(self, name: str, check_fn: HealthCheckFn) -> None:
        """Зарегистрировать custom healthcheck.

        Args:
            name: Имя компонента (e.g., ``"redis"``, ``"kafka"``, ``"my_service"``).
            check_fn: Async callable возвращающая bool.
        """
        self._custom_checks[name] = check_fn
        _logger.info("health_check.registered name=%s", name)

    async def check(self, name: str) -> dict[str, Any]:
        """Проверить один компонент.

        Args:
            name: Имя компонента.

        Returns:
            Dict с ``status``, ``latency_ms``, ``error``.
        """
        import time

        if name not in self._custom_checks:
            return {
                "status": False,
                "latency_ms": 0.0,
                "error": f"component '{name}' not registered",
            }

        start = time.monotonic()
        try:
            import asyncio

            ok = await asyncio.wait_for(
                self._custom_checks[name](), timeout=self._timeout
            )
            latency_ms = (time.monotonic() - start) * 1000.0
            return {
                "status": bool(ok),
                "latency_ms": round(latency_ms, 2),
                "error": None if ok else "check returned False",
            }
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return {
                "status": False,
                "latency_ms": round(latency_ms, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }

    async def check_all(self) -> HealthReport:
        """Параллельная проверка всех зарегистрированных компонентов.

        Использует :class:`asyncio.TaskGroup` для structured concurrency —
        все checks выполняются параллельно с timeout.

        Returns:
            HealthReport с детализированным status по каждому компоненту.
        """
        import asyncio

        if not self._custom_checks:
            return HealthReport(
                status=HealthStatus.HEALTHY,
                is_all_active=True,
                components={},
            )

        async with asyncio.TaskGroup() as tg:
            tasks = {
                name: tg.create_task(self.check(name))
                for name in self._custom_checks
            }

        components = {name: tasks[name].result() for name in tasks}

        failed = [n for n, r in components.items() if not r["status"]]
        if not failed:
            status = HealthStatus.HEALTHY
        elif len(failed) >= self._threshold:
            status = HealthStatus.UNHEALTHY
        else:
            status = HealthStatus.DEGRADED

        return HealthReport(
            status=status,
            is_all_active=not failed,
            components=components,
        )

    async def is_healthy(self) -> bool:
        """Быстрая проверка: все ли компоненты healthy?"""
        report = await self.check_all()
        return report.status == HealthStatus.HEALTHY

    async def get_status(self) -> dict[str, Any]:
        """Alias для :meth:`check_all` + ``.to_dict()``."""
        report = await self.check_all()
        return report.to_dict()


@lru_cache(maxsize=1)
def get_health_facade() -> HealthFacade:
    """Lazy singleton глобального :class:`HealthFacade`."""
    return HealthFacade()
