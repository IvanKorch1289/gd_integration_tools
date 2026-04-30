"""Health-check провайдеры для ResilienceCoordinator (W26.2).

Каждая зарегистрированная функция — async callable, возвращающий dict с
полями ``status`` / ``mode`` / ``details``, совместимый с протоколом
``HealthAggregator``.

Пример итогового вывода ``/components?mode=deep``:

.. code-block:: json

    {
        "status": "degraded",
        "components": {
            "db_main": {
                "status": "degraded",
                "details": {
                    "breaker_state": "open",
                    "fallback_mode": "auto",
                    "chain": ["sqlite_ro"],
                    "last_used_backend": "sqlite_ro",
                    "degradation": "degraded"
                }
            }
        }
    }

Соответствие статусов (Правило: CB OPEN+fallback=degraded;
CB OPEN без fallback=down):

* ``normal``   → ``ok``
* ``degraded`` → ``degraded``
* ``down``     → ``error``
"""

from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.resilience.coordinator import (
    ComponentStatus,
    ResilienceCoordinator,
    get_resilience_coordinator,
)

__all__ = (
    "build_resilience_health_check",
    "register_resilience_health_checks",
    "resilience_components_report",
)

logger = logging.getLogger(__name__)


_STATUS_MAP: dict[str, str] = {
    "normal": "ok",
    "degraded": "degraded",
    "down": "error",
}


def _component_to_dict(component: ComponentStatus) -> dict[str, Any]:
    """Преобразует ``ComponentStatus`` в health-check dict."""
    return {
        "name": component.name,
        "status": _STATUS_MAP[component.degradation],
        "details": {
            "breaker_state": component.breaker_state,
            "fallback_mode": component.mode,
            "chain": list(component.chain),
            "last_used_backend": component.last_used_backend,
            "degradation": component.degradation,
        },
    }


def build_resilience_health_check(
    component: str, coordinator: ResilienceCoordinator | None = None
):
    """Возвращает async health-check callable для одного компонента.

    Используется ``HealthAggregator.register(name, fn)`` — coordinator
    читается лениво при каждом вызове, так что регистрация может
    выполняться до полной инициализации singleton'а.
    """

    async def _check(*, mode: str = "fast") -> dict[str, Any]:
        # ``mode`` принимается, но игнорируется: данные coordinator-а
        # предсчитаны (state-machine purgatory), нет смысла различать.
        coord = coordinator or get_resilience_coordinator()
        snapshot = coord.status().get(component)
        if snapshot is None:
            return {
                "name": component,
                "status": "unknown",
                "error": "component not registered in ResilienceCoordinator",
                "mode": mode,
            }
        result = _component_to_dict(snapshot)
        result["mode"] = mode
        return result

    return _check


def register_resilience_health_checks(
    health_aggregator: Any, coordinator: ResilienceCoordinator | None = None
) -> None:
    """Регистрирует health-checks для всех 11 компонентов W26.

    Идемпотентно: повторный вызов перерегистрирует callbacks.
    ``health_aggregator`` принимается типа Any, чтобы избежать
    циклических импортов модулей ``application/`` ↔ ``resilience/``.
    """
    coord = coordinator or get_resilience_coordinator()
    for component in coord.list_components():
        health_aggregator.register(
            component, build_resilience_health_check(component, coord)
        )
    logger.info(
        "Resilience: registered %d health-checks", len(coord.list_components())
    )


def resilience_components_report(
    coordinator: ResilienceCoordinator | None = None,
) -> dict[str, dict[str, Any]]:
    """Снимок состояния всех компонентов (для /components?mode=deep)."""
    coord = coordinator or get_resilience_coordinator()
    return {name: _component_to_dict(comp) for name, comp in coord.status().items()}
