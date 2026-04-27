"""Circuit Breaker Registry — именованные breakers для всех I/O клиентов."""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces import CircuitBreaker, CircuitBreakerConfig

__all__ = ("CircuitBreakerRegistry", "breaker_registry")

logger = logging.getLogger(__name__)


class CircuitBreakerRegistry:
    """Реестр именованных circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
            logger.info("Circuit breaker created: %s", name)
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        return self._breakers.get(name)

    def list_states(self) -> dict[str, str]:
        return {name: cb.state.value for name, cb in self._breakers.items()}

    def get_all_status(self) -> list[dict[str, Any]]:
        result = []
        for name, cb in self._breakers.items():
            result.append(
                {
                    "name": name,
                    "state": cb.state.value,
                    "failure_count": cb._failure_count,
                }
            )
        return result


breaker_registry = CircuitBreakerRegistry()

breaker_registry.get_or_create("redis")
breaker_registry.get_or_create("db_main")
breaker_registry.get_or_create("s3")
breaker_registry.get_or_create(
    "clickhouse", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=15.0)
)
breaker_registry.get_or_create(
    "elasticsearch", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=15.0)
)
breaker_registry.get_or_create(
    "mongodb", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=15.0)
)
