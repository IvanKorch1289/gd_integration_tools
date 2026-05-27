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
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable

__all__ = (
    "ComponentState",
    "DegradationManager",
    "DegradationMode",
    "DegradationTransition",
    "degradation_manager",
    "mode_at_least",
)

logger = logging.getLogger(__name__)


class DegradationMode(Enum):
    """Режим деградации приложения (S13 K2 W4).

    5 уровней строгости (от лёгкого к жёсткому):

    * ``FULL`` — всё работает;
    * ``READ_ONLY`` — блок POST/PATCH/DELETE на ``/api/v1/*``;
    * ``CACHE_ONLY`` — read-only + force ``cache_first=true`` на GET;
    * ``ESSENTIAL_ONLY`` — только tech/health-эндпоинты;
    * ``MAINTENANCE`` — всё, кроме ``/health/liveness`` и ``/tech/degradation/level``.

    Legacy alias'ы ``DEGRADED`` / ``EMERGENCY`` сохранены для backward compat.
    """

    FULL = "full"
    DEGRADED = "degraded"  # backward-compat alias для READ_ONLY
    READ_ONLY = "read_only"
    CACHE_ONLY = "cache_only"
    EMERGENCY = "emergency"  # backward-compat alias для ESSENTIAL_ONLY
    ESSENTIAL_ONLY = "essential_only"
    MAINTENANCE = "maintenance"


_MODE_STRICTNESS: dict[DegradationMode, int] = {
    DegradationMode.FULL: 0,
    DegradationMode.DEGRADED: 1,
    DegradationMode.READ_ONLY: 1,
    DegradationMode.CACHE_ONLY: 2,
    DegradationMode.EMERGENCY: 3,
    DegradationMode.ESSENTIAL_ONLY: 3,
    DegradationMode.MAINTENANCE: 4,
}


def mode_at_least(current: DegradationMode, threshold: DegradationMode) -> bool:
    """True, если ``current`` имеет уровень строгости >= ``threshold``."""
    return _MODE_STRICTNESS[current] >= _MODE_STRICTNESS[threshold]


@dataclass(frozen=True, slots=True)
class DegradationTransition:
    """Запись о переключении DegradationMode (S13 K2 W4)."""

    timestamp_utc: str
    from_mode: str
    to_mode: str
    actor: str
    reason: str


@dataclass(slots=True)
class ComponentState:
    """Состояние компонента в DegradationManager."""

    name: str
    available: bool = True
    last_check: float = 0.0
    failure_count: int = 0
    fallback_active: bool = False


class DegradationManager:
    """Управляет graceful degradation при недоступности компонентов.

    S13 K2 W4: добавлен manual switch (set_mode) + история переключений +
    опциональная persistence через :class:`DegradationStateStore`.
    """

    def __init__(self) -> None:
        self._components: dict[str, ComponentState] = {}
        self._fallbacks: dict[str, Callable[..., Any]] = {}
        self._manual_mode: DegradationMode | None = None
        self._history: deque[DegradationTransition] = deque(maxlen=100)
        self._store: Any = None

    def attach_store(self, store: Any) -> None:
        """Подключить :class:`DegradationStateStore` для persistence."""
        self._store = store

    async def set_mode(
        self, mode: DegradationMode, *, actor: str = "system", reason: str = ""
    ) -> DegradationTransition:
        """Ручной switch DegradationMode (S13 K2 W4).

        Persists через ``store`` если подключён + пишет в history.
        Возвращает запись о transition.
        """
        previous = self._manual_mode or self.mode()
        self._manual_mode = mode
        transition = DegradationTransition(
            timestamp_utc=datetime.now(UTC).isoformat(),
            from_mode=previous.value,
            to_mode=mode.value,
            actor=actor,
            reason=reason,
        )
        self._history.append(transition)
        logger.warning(
            "degradation.mode_changed",
            extra={
                "from": previous.value,
                "to": mode.value,
                "actor": actor,
                "reason": reason,
            },
        )
        if self._store is not None:
            try:
                await self._store.persist(mode, transition)
            except Exception as _:  # noqa: BLE001
                logger.exception("degradation.store_persist_failed")
        return transition

    def history(self, n: int = 20) -> list[DegradationTransition]:
        """Последние ``n`` transitions."""
        return list(self._history)[-n:]

    @property
    def current_mode(self) -> DegradationMode:
        """Текущий effective mode (manual > auto)."""
        return self._manual_mode if self._manual_mode is not None else self.mode()

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
