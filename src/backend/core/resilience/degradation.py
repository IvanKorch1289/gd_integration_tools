"""Graceful degradation manager.

При падении Redis/DB приложение продолжает работать с деградацией:
- Fallback на in-memory cache
- Rate limiting отключается (fail-open)
- Sessions храним в памяти

Sprint 1 V16 Single-Entry: модуль вынесен из ``core/resilience.py``
в одноимённый package для совместного с unified ``CircuitBreaker`` /
``RateLimiter`` / ``Retry`` (Step 3.2).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

__all__ = (
    "ComponentState",
    "DegradationManager",
    "DegradationMode",
    "degradation_manager",
)

logger = logging.getLogger(__name__)


class DegradationMode(Enum):
    """Режим деградации приложения."""

    FULL = "full"  # Всё работает
    DEGRADED = "degraded"  # Часть функций отключена
    EMERGENCY = "emergency"  # Только критичные функции


@dataclass(slots=True)
class ComponentState:
    """Состояние компонента в DegradationManager."""

    name: str
    available: bool = True
    last_check: float = 0.0
    failure_count: int = 0
    fallback_active: bool = False


class DegradationManager:
    """Управляет graceful degradation при недоступности компонентов."""

    def __init__(self) -> None:
        self._components: dict[str, ComponentState] = {}
        self._fallbacks: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fallback: Callable[..., Any] | None = None) -> None:
        self._components[name] = ComponentState(name=name)
        if fallback:
            self._fallbacks[name] = fallback

    def report_failure(self, name: str) -> None:
        if name not in self._components:
            self.register(name)
        state = self._components[name]
        state.failure_count += 1
        state.last_check = time.monotonic()
        if state.failure_count >= 3 and state.available:
            state.available = False
            state.fallback_active = True
            logger.warning("Component '%s' degraded — activating fallback", name)

    def report_success(self, name: str) -> None:
        if name not in self._components:
            self.register(name)
        state = self._components[name]
        if not state.available:
            logger.info("Component '%s' recovered", name)
        state.available = True
        state.failure_count = 0
        state.fallback_active = False

    def get_fallback(self, name: str) -> Callable[..., Any] | None:
        return (
            self._fallbacks.get(name)
            if name in self._components and self._components[name].fallback_active
            else None
        )

    def is_available(self, name: str) -> bool:
        return self._components.get(name, ComponentState(name=name)).available

    def mode(self) -> DegradationMode:
        critical = ["database", "redis"]
        critical_down = sum(
            1
            for n in critical
            if n in self._components and not self._components[n].available
        )
        if critical_down >= 2:
            return DegradationMode.EMERGENCY
        if critical_down >= 1 or any(
            not s.available for s in self._components.values()
        ):
            return DegradationMode.DEGRADED
        return DegradationMode.FULL

    def report(self) -> dict[str, Any]:
        return {
            "mode": self.mode().value,
            "components": {
                name: {
                    "available": state.available,
                    "failures": state.failure_count,
                    "fallback_active": state.fallback_active,
                }
                for name, state in self._components.items()
            },
        }


degradation_manager = DegradationManager()
