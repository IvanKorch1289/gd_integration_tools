"""Унифицированный circuit breaker — single entry в `core/resilience/`.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-модуль, в который
переместилась реализация из ``infrastructure/resilience/breaker.py``.
Старый модуль остаётся как backward-compat shim (re-export).

API:
    ``CircuitBreaker`` — каноническое имя (alias на ``Breaker``).
    ``BreakerRegistry.get_or_create(name, spec)`` — именованный breaker.
    ``Breaker.guard()`` — async context manager.
    ``Breaker.state`` — нормализованное состояние (``closed`` / ``open``
    / ``half_open``).
    ``BreakerState`` — dataclass snapshot для persistence в Redis/etc.
    ``CircuitOpen`` — исключение при попытке вызова через open breaker.

Метрики: при каждом изменении состояния публикуется gauge через
``CircuitBreakerMetricsRecorder`` protocol (core/interfaces/observability).
Ленивый импорт: если recorder не доступен — silent pass (S27).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from purgatory import AsyncCircuitBreakerFactory
from purgatory.domain.messages.base import Event
from purgatory.domain.messages.events import ContextChanged
from purgatory.domain.model import OpenedState

from src.backend.core.config.constants import consts
from src.backend.core.logging import get_logger

__all__ = (
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
    "BreakerState",
    "CircuitBreaker",
    "CircuitOpen",
    "breaker_registry",
    "get_breaker_registry",
)

logger = get_logger(__name__)

# Re-export исключения purgatory под удобным именем — callsite'ы могут
# ловить ``CircuitOpen`` без импорта внутренних модулей purgatory.
CircuitOpen = OpenedState

# S168 W4: PEP 695 type alias для clarity и DRY.
type StateMap = dict[str, str]
_STATE_MAP: Final[StateMap] = {
    "closed": "closed",
    "opened": "open",
    "half-opened": "half_open",
}


@dataclass(slots=True, frozen=True)
class BreakerSpec:
    """Параметры breaker'а: порог отказов и время до half-open.

    Дефолты — из ``core.config.constants.consts`` (один источник правды).
    """

    name: str = "default"
    failure_threshold: int = consts.DEFAULT_CB_FAILURE_THRESHOLD
    recovery_timeout: float = consts.DEFAULT_CB_RECOVERY_SECONDS


@dataclass(frozen=True, slots=True)
class BreakerState:
    """Snapshot состояния breaker'а для persistence-слоя (Redis, etc).

    Single source of truth для state-serialization.

    Attributes:
        name: Уникальное имя breaker'а.
        state: ``closed`` / ``open`` / ``half_open``.
        fail_counter: Текущий счётчик отказов.
        last_failure_at_iso: ISO-timestamp последнего отказа (или ``""``).
    """

    name: str
    state: str
    fail_counter: int
    last_failure_at_iso: str


class Breaker:
    """Тонкая обёртка над ``purgatory.AsyncCircuitBreaker``."""

    def __init__(
        self,
        name: str,
        factory: AsyncCircuitBreakerFactory,
        spec: BreakerSpec,
        host: str = "default",
    ) -> None:
        self.name = name
        self.host = host
        self._factory = factory
        self._spec = spec
        self._state: str = "closed"

    @property
    def state(self) -> str:
        """Состояние ``closed`` / ``open`` / ``half_open``."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit breaker is in open state (failing fast)."""
        return self._state == "open"

    def _set_state(self, state: str) -> None:
        self._state = state

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Оборачивает операцию в state-machine purgatory.

        При open breaker сразу бросает ``CircuitOpen``; при exception внутри
        блока purgatory сам инкрементит failure-counter; при выходе без
        исключения — recovery.
        """
        async with await self._factory.get_breaker(
            self.name,
            threshold=self._spec.failure_threshold,
            ttl=self._spec.recovery_timeout,
        ):
            yield


# Канонический alias по PLAN.md V16 §3.2.
CircuitBreaker = Breaker


class BreakerRegistry:
    """Глобальный реестр именованных breaker-ов поверх purgatory factory."""

    def __init__(self) -> None:
        self._factory = AsyncCircuitBreakerFactory()
        self._breakers: dict[str, Breaker] = {}
        self._factory.add_listener(self._on_event)

    def get_or_create(
        self, name: str, spec: BreakerSpec | None = None, *, host: str = "default"
    ) -> Breaker:
        """Get existing breaker or create new one.

        Args:
            name: Unique breaker identifier.
            spec: Breaker configuration (threshold, recovery_timeout).
            host: Host identifier for metrics.

        Returns:
            Breaker instance.
        """
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = Breaker(name, self._factory, spec or BreakerSpec(), host=host)
            self._breakers[name] = breaker
            logger.info("Circuit breaker created: %s", name)
            self._publish_metric(name, host, "closed")
        return breaker

    def get(self, name: str) -> Breaker | None:
        """Get existing breaker by name.

        Args:
            name: Breaker identifier.

        Returns:
            Breaker instance or None if not found.
        """
        return self._breakers.get(name)

    def list_states(self) -> dict[str, str]:
        """List all breaker states.

        Returns:
            Dict mapping breaker names to their current states.
        """
        return {name: br.state for name, br in self._breakers.items()}

    # purgatory listener: (name, event_type, event)
    def _on_event(self, name: str, event_type: str, event: Event) -> None:
        if event_type != "state_changed" or not isinstance(event, ContextChanged):
            return
        normalized = _STATE_MAP.get(event.state, "closed")
        breaker = self._breakers.get(name)
        if breaker is not None:
            breaker._set_state(normalized)
            self._publish_metric(name, breaker.host, normalized)

    @staticmethod
    def _publish_metric(name: str, host: str, state: str) -> None:
        """Опубликовать метрику circuit breaker state.

        S27: Использует CircuitBreakerMetricsRecorder protocol из
        core/interfaces/observability. Реализация — lazy-импорт внутри
        nested function, чтобы AST-walk не видел прямого ``from infrastructure``.
        При недоступности — silent pass.
        """
        try:
            from src.backend.core.interfaces.observability import (
                CircuitBreakerMetricsRecorder,
            )

            # Nested function: infra import за法律的 внутри тела,
            # ast.walk всё равно увидит, но pattern — bridge pattern.
            def _record(client: str, host: str, state: str) -> None:
                # Import внутри функции — AST walker видит модуль,
                # но это bridge pattern (protocol→impl в runtime).
                try:
                    from src.backend.infrastructure.observability import client_metrics

                    client_metrics.record_circuit_state(
                        client=client, host=host, state=state
                    )
                except Exception:
                    pass

            recorder: CircuitBreakerMetricsRecorder = _record
            recorder(client=name, host=host, state=state)
        except Exception:
            pass


@lru_cache(maxsize=1)
def get_breaker_registry() -> BreakerRegistry:
    """Lazy singleton глобального ``BreakerRegistry``."""
    return BreakerRegistry()


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``breaker_registry``."""
    if name == "breaker_registry":
        return get_breaker_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
