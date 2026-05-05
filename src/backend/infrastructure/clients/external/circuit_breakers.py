"""Pre-registered breakers для всех внешних I/O клиентов (поверх фасада)."""

import logging
from functools import lru_cache
from typing import Any

from src.core.config.constants import consts
from src.infrastructure.resilience.breaker import (
    Breaker,
    BreakerSpec,
    get_breaker_registry,
)

__all__ = ("CircuitBreakerRegistry", "breaker_registry", "get_circuit_breaker_registry")

logger = logging.getLogger(__name__)


class CircuitBreakerRegistry:
    """Тонкий адаптер над единым ``BreakerRegistry`` (Wave 6.1).

    Сохраняет API ``get_or_create / get / list_states / get_all_status``
    для совместимости со старыми callsite-ами; внутри делегирует в фасад.
    """

    def get_or_create(self, name: str, spec: BreakerSpec | None = None) -> Breaker:
        return get_breaker_registry().get_or_create(name, spec)

    def get(self, name: str) -> Breaker | None:
        return get_breaker_registry().get(name)

    def list_states(self) -> dict[str, str]:
        return get_breaker_registry().list_states()

    def get_all_status(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "state": state}
            for name, state in get_breaker_registry().list_states().items()
        ]


@lru_cache(maxsize=1)
def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Lazy singleton + pre-register каноничных breakers (Wave 6.1)."""
    registry = CircuitBreakerRegistry()
    # Pre-registered breakers для канонических зависимостей.
    registry.get_or_create("redis")
    registry.get_or_create("db_main")
    registry.get_or_create("s3")
    fast = BreakerSpec(
        failure_threshold=consts.DEFAULT_CB_FAST_FAILURE_THRESHOLD,
        recovery_timeout=consts.DEFAULT_CB_FAST_RECOVERY_SECONDS,
    )
    registry.get_or_create("clickhouse", fast)
    registry.get_or_create("elasticsearch", fast)
    registry.get_or_create("mongodb", fast)
    return registry


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat."""
    if name == "breaker_registry":
        return get_circuit_breaker_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
