"""Унифицированный circuit breaker поверх ``purgatory``.

Wave 6.1: единый фасад вместо трёх параллельных реализаций
(``core.utils.circuit_breaker``, ``infrastructure.resilience.client_breaker``,
``infrastructure.clients.external.circuit_breakers``).

API:
    ``BreakerRegistry.get_or_create(name, spec)`` — именованный breaker.
    ``Breaker.guard()`` — async context manager.
    ``Breaker.state`` — нормализованное состояние (``closed``/``open``/``half_open``).
    ``CircuitOpen`` — исключение при попытке вызова через open breaker.

Метрики: при каждом изменении состояния публикуется gauge через
``infrastructure.observability.client_metrics.record_circuit_state``.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, AsyncIterator, Final

from purgatory import AsyncCircuitBreakerFactory
from purgatory.domain.messages.base import Event
from purgatory.domain.messages.events import ContextChanged
from purgatory.domain.model import OpenedState

from src.backend.core.config.constants import consts

__all__ = (
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
    "CircuitOpen",
    "breaker_registry",
    "get_breaker_registry",
)

logger = logging.getLogger(__name__)

# Re-export исключения purgatory под удобным именем — callsite'ы могут
# ловить ``CircuitOpen`` без импорта внутренних модулей purgatory.
CircuitOpen = OpenedState

_STATE_MAP: Final[dict[str, str]] = {
    "closed": "closed",
    "opened": "open",
    "half-opened": "half_open",
}


@dataclass(slots=True, frozen=True)
class BreakerSpec:
    """Параметры breaker'а: порог отказов и время до half-open.

    Дефолты — из ``core.config.constants.consts`` (один источник правды).
    """

    failure_threshold: int = consts.DEFAULT_CB_FAILURE_THRESHOLD
    recovery_timeout: float = consts.DEFAULT_CB_RECOVERY_SECONDS


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


class BreakerRegistry:
    """Глобальный реестр именованных breaker-ов поверх purgatory factory."""

    def __init__(self) -> None:
        self._factory = AsyncCircuitBreakerFactory()
        self._breakers: dict[str, Breaker] = {}
        self._factory.add_listener(self._on_event)

    def get_or_create(
        self, name: str, spec: BreakerSpec | None = None, *, host: str = "default"
    ) -> Breaker:
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = Breaker(name, self._factory, spec or BreakerSpec(), host=host)
            self._breakers[name] = breaker
            logger.info("Circuit breaker created: %s", name)
            self._publish_metric(name, host, "closed")
        return breaker

    def get(self, name: str) -> Breaker | None:
        return self._breakers.get(name)

    def list_states(self) -> dict[str, str]:
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
        try:
            from src.backend.infrastructure.observability.client_metrics import (
                record_circuit_state,
            )

            record_circuit_state(client=name, host=host, state=state)  # type: ignore[arg-type]
        except ImportError:
            pass


@lru_cache(maxsize=1)
def get_breaker_registry() -> "BreakerRegistry":
    """Lazy singleton глобального ``BreakerRegistry`` (Wave 6.1)."""
    return BreakerRegistry()


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``breaker_registry``."""
    if name == "breaker_registry":
        return get_breaker_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
