"""Health Aggregator — параллельный опрос всех клиентов для /health endpoint.

Возвращает unified JSON:
    {
        "status": "ok" | "degraded" | "down",
        "timestamp": "...",
        "mode": "fast" | "deep",
        "components": {
            "redis": {"status": "ok", "latency_ms": 2.3, "error": null},
            "database": {"status": "ok", "latency_ms": 5.1, "error": null},
            ...
        }
    }

Используется для Kubernetes liveness (fast) и readiness (deep) probes.

IL1.6 (ADR-022): добавлен ``mode: "fast" | "deep"``.
* ``fast`` — быстрый PING (SLA < 100ms), для K8s liveness.
* ``deep`` — smoke-operation (SLA < 2s), для readiness и on-demand dashboard.
Каждая зарегистрированная check-функция может поддерживать kwarg ``mode`` —
aggregator пробросит его через inspect. Клиенты ABC (``InfrastructureClient``)
из ``ConnectorRegistry`` интегрируются автоматически через
``include_registry()``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

if TYPE_CHECKING:
    from src.infrastructure.clients.base_connector import HealthMode

__all__ = ("HealthAggregator", "get_health_aggregator")

logger = logging.getLogger("infra.health")

HealthMode = Literal["fast", "deep"]  # noqa: F811  (re-export для удобства)

#: Legacy-сигнатура (backward-compat): функция без аргументов, возвращает dict.
#: Новая сигнатура может принимать kwarg ``mode`` — aggregator прокинет его
#: автоматически через inspect.
HealthCheckFn = Callable[..., Awaitable[dict[str, Any]]]


#: SLA-timeout per-check в зависимости от режима (seconds). Конкретная
#: реализация client.health(mode) должна укладываться в эти бюджеты.
_TIMEOUT_BY_MODE: dict[HealthMode, float] = {"fast": 1.0, "deep": 2.5}


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
        #: Legacy-timeout. Для режимных probes используется `_TIMEOUT_BY_MODE`.
        self._timeout = timeout_seconds
        self._include_registry: bool = False
        #: Wave 6.4: предыдущий overall-статус для детекции переходов.
        self._last_overall: str | None = None

    def register(self, name: str, health_fn: HealthCheckFn) -> None:
        """Регистрирует health-check функцию. Должна возвращать dict со status."""
        self._checks[name] = health_fn
        logger.debug("Health check registered: %s", name)

    def unregister(self, name: str) -> None:
        """Удаляет health-check."""
        self._checks.pop(name, None)

    def include_registry(self, enabled: bool = True) -> None:
        """Автоматически включать ``ConnectorRegistry.health_all()`` в отчёт.

        Предпочтительный путь для новых infrastructure-клиентов (ABC
        ``InfrastructureClient``). Legacy-check-функции, зарегистрированные
        через ``register()``, продолжают работать рядом.
        """
        self._include_registry = enabled

    def list_components(self) -> list[str]:
        return sorted(self._checks.keys())

    @staticmethod
    def _supports_mode_kwarg(fn: HealthCheckFn) -> bool:
        """Определить, принимает ли callable kwarg ``mode``."""
        try:
            sig = inspect.signature(fn)
        except TypeError, ValueError:
            return False
        return "mode" in sig.parameters

    async def _safe_check(
        self, name: str, fn: HealthCheckFn, *, mode: HealthMode = "fast"
    ) -> dict[str, Any]:
        """Выполняет один health-check с timeout."""
        timeout = _TIMEOUT_BY_MODE.get(mode, self._timeout)
        try:
            coro = fn(mode=mode) if self._supports_mode_kwarg(fn) else fn()
            result = await asyncio.wait_for(coro, timeout=timeout)
            if not isinstance(result, dict):
                return {
                    "name": name,
                    "status": "error",
                    "error": f"Invalid result type: {type(result).__name__}",
                    "mode": mode,
                }
            result.setdefault("name", name)
            result.setdefault("status", "unknown")
            result.setdefault("mode", mode)
            return result
        except asyncio.TimeoutError:
            return {
                "name": name,
                "status": "error",
                "error": f"Timeout after {timeout}s ({mode})",
                "latency_ms": timeout * 1000,
                "mode": mode,
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "error",
                "error": str(exc)[:200],
                "mode": mode,
            }

    async def _collect_registry_components(
        self, mode: HealthMode
    ) -> dict[str, dict[str, Any]]:
        """Собрать health-отчёты из ConnectorRegistry (если включено).

        Преобразует HealthResult → dict с полями совместимыми с legacy
        check-функциями.
        """
        if not self._include_registry:
            return {}
        try:
            from src.infrastructure.registry import ConnectorRegistry
        except ImportError:
            return {}
        registry = ConnectorRegistry.instance()
        names = registry.names()
        if not names:
            return {}
        try:
            results = await registry.health_all(mode=mode)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ConnectorRegistry.health_all failed: %s", exc)
            return {}
        out: dict[str, dict[str, Any]] = {}
        for name, r in results.items():
            out[name] = {
                "name": name,
                "status": "ok"
                if r.status == "ok"
                else ("degraded" if r.status == "degraded" else "error"),
                "latency_ms": r.latency_ms,
                "mode": r.mode,
                "details": r.details,
                "error": r.error,
            }
        return out

    async def check_all(self, *, mode: HealthMode = "fast") -> dict[str, Any]:
        """Параллельный опрос всех зарегистрированных компонентов."""
        legacy_tasks = [
            self._safe_check(name, fn, mode=mode) for name, fn in self._checks.items()
        ]
        legacy_results_coro = (
            asyncio.gather(*legacy_tasks)
            if legacy_tasks
            else asyncio.sleep(0, result=[])
        )
        registry_coro = self._collect_registry_components(mode)
        legacy_results, registry_results = await asyncio.gather(
            legacy_results_coro, registry_coro
        )

        components: dict[str, dict[str, Any]] = {}
        # Сначала registry-компоненты, потом legacy (legacy может override
        # registry-имени — полезно, если кастомный check подменяет дефолт).
        for name, comp in registry_results.items():
            components[name] = comp
        for comp in legacy_results or []:
            name = comp.get("name", "unknown")
            components[name] = comp

        if not components:
            return {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
                "mode": mode,
                "components": {},
                "message": "No health checks registered",
            }

        overall = "ok"
        for comp in components.values():
            status = comp.get("status", "unknown")
            if status == "error":
                overall = "down"
            elif status in ("degraded", "unknown") and overall == "ok":
                overall = "degraded"

        # Wave 6.4: публикация перехода overall-статуса в EventBus.
        await self._maybe_publish_transition(overall, components)

        return {
            "status": overall,
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": mode,
            "components": components,
        }

    async def _maybe_publish_transition(
        self, current: str, components: dict[str, dict[str, Any]]
    ) -> None:
        """Публикует событие при смене overall-статуса (ok ↔ degraded ↔ down)."""
        previous = self._last_overall
        self._last_overall = current
        if previous is None or previous == current:
            return
        try:
            from src.infrastructure.clients.messaging.event_bus import get_event_bus
            from src.schemas.health_events import HealthTransitionEvent

            bus = get_event_bus()
            event = HealthTransitionEvent(
                previous_status=previous,
                current_status=current,
                components=components,
            )
            await bus.publish("events.health", event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Health transition publish skipped: %s", exc)

    async def check_single(
        self, name: str, *, mode: HealthMode = "fast"
    ) -> dict[str, Any]:
        """Проверка одного компонента по имени."""
        fn = self._checks.get(name)
        if fn is not None:
            return await self._safe_check(name, fn, mode=mode)
        # Попробовать через ConnectorRegistry.
        if self._include_registry:
            try:
                from src.infrastructure.registry import ConnectorRegistry

                client = ConnectorRegistry.instance().get(name)
            except Exception:  # noqa: BLE001
                return {
                    "name": name,
                    "status": "error",
                    "error": "Component not registered",
                }
            try:
                r = await client.health(mode=mode)
                return {
                    "name": name,
                    "status": "ok" if r.status == "ok" else "error",
                    "latency_ms": r.latency_ms,
                    "mode": r.mode,
                    "details": r.details,
                    "error": r.error,
                }
            except Exception as exc:  # noqa: BLE001
                return {"name": name, "status": "error", "error": str(exc)[:200]}
        return {"name": name, "status": "error", "error": "Component not registered"}


_aggregator: HealthAggregator | None = None


def get_health_aggregator() -> HealthAggregator:
    """Singleton для приложения."""
    global _aggregator
    if _aggregator is None:
        _aggregator = HealthAggregator()
    return _aggregator
