"""Health Aggregator — параллельный опрос всех клиентов для /health endpoint.

Возвращает unified JSON:
    {
        "status": "ok" | "degraded" | "down",
        "timestamp": "...",
        "components": {
            "redis": {"status": "ok", "latency_ms": 2.3, "error": null},
            "database": {"status": "ok", "latency_ms": 5.1, "error": null},
            ...
        }
    }

Используется для Kubernetes liveness/readiness probes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

__all__ = ("HealthAggregator", "get_health_aggregator")

logger = logging.getLogger("infra.health")

HealthCheckFn = Callable[[], Awaitable[dict[str, Any]]]


class HealthAggregator:
    """Реестр health-check функций + параллельный опрос.

    Регистрация::

        health_aggregator.register("redis", redis_client.health_check)
        health_aggregator.register("db_main", db_client.health_check)

    Использование в /health endpoint::

        report = await health_aggregator.check_all()
    """

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._checks: dict[str, HealthCheckFn] = {}
        self._timeout = timeout_seconds

    def register(self, name: str, health_fn: HealthCheckFn) -> None:
        """Регистрирует health-check функцию. Должна возвращать dict со status."""
        self._checks[name] = health_fn
        logger.debug("Health check registered: %s", name)

    def unregister(self, name: str) -> None:
        """Удаляет health-check."""
        self._checks.pop(name, None)

    def list_components(self) -> list[str]:
        return sorted(self._checks.keys())

    async def _safe_check(self, name: str, fn: HealthCheckFn) -> dict[str, Any]:
        """Выполняет один health-check с timeout."""
        try:
            result = await asyncio.wait_for(fn(), timeout=self._timeout)
            if not isinstance(result, dict):
                return {
                    "name": name,
                    "status": "error",
                    "error": f"Invalid result type: {type(result).__name__}",
                }
            result.setdefault("name", name)
            result.setdefault("status", "unknown")
            return result
        except asyncio.TimeoutError:
            return {
                "name": name,
                "status": "error",
                "error": f"Timeout after {self._timeout}s",
                "latency_ms": self._timeout * 1000,
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "error",
                "error": str(exc)[:200],
            }

    async def check_all(self) -> dict[str, Any]:
        """Параллельный опрос всех зарегистрированных компонентов."""
        if not self._checks:
            return {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
                "components": {},
                "message": "No health checks registered",
            }

        tasks = [
            self._safe_check(name, fn)
            for name, fn in self._checks.items()
        ]
        results = await asyncio.gather(*tasks)

        components: dict[str, dict[str, Any]] = {}
        overall = "ok"
        for comp in results:
            name = comp.get("name", "unknown")
            components[name] = comp
            status = comp.get("status", "unknown")
            if status == "error":
                overall = "down" if overall != "down" else overall
            elif status in ("degraded", "unknown") and overall == "ok":
                overall = "degraded"

        return {
            "status": overall,
            "timestamp": datetime.now(UTC).isoformat(),
            "components": components,
        }

    async def check_single(self, name: str) -> dict[str, Any]:
        """Проверка одного компонента по имени."""
        fn = self._checks.get(name)
        if fn is None:
            return {"name": name, "status": "error", "error": "Component not registered"}
        return await self._safe_check(name, fn)


_aggregator: HealthAggregator | None = None


def get_health_aggregator() -> HealthAggregator:
    """Singleton для приложения."""
    global _aggregator
    if _aggregator is None:
        _aggregator = HealthAggregator()
    return _aggregator
