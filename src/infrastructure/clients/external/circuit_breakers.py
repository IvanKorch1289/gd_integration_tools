"""Pre-registered breakers для всех внешних I/O клиентов (поверх фасада)."""


import logging
from typing import Any

from src.core.config.constants import consts
from src.infrastructure.resilience.breaker import Breaker, BreakerSpec
from src.infrastructure.resilience.breaker import breaker_registry as _facade_registry

__all__ = ("CircuitBreakerRegistry", "breaker_registry")

logger = logging.getLogger(__name__)


class CircuitBreakerRegistry:
    """Тонкий адаптер над единым ``BreakerRegistry`` (Wave 6.1).

    Сохраняет API ``get_or_create / get / list_states / get_all_status``
    для совместимости со старыми callsite-ами; внутри делегирует в фасад.
    """

    def get_or_create(
        self, name: str, spec: BreakerSpec | None = None
    ) -> Breaker:
        return _facade_registry.get_or_create(name, spec)

    def get(self, name: str) -> Breaker | None:
        return _facade_registry.get(name)

    def list_states(self) -> dict[str, str]:
        return _facade_registry.list_states()

    def get_all_status(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "state": state}
            for name, state in _facade_registry.list_states().items()
        ]


breaker_registry = CircuitBreakerRegistry()

# Pre-registered breakers для канонических зависимостей.
breaker_registry.get_or_create("redis")
breaker_registry.get_or_create("db_main")
breaker_registry.get_or_create("s3")
_FAST = BreakerSpec(
    failure_threshold=consts.DEFAULT_CB_FAST_FAILURE_THRESHOLD,
    recovery_timeout=consts.DEFAULT_CB_FAST_RECOVERY_SECONDS,
)
breaker_registry.get_or_create("clickhouse", _FAST)
breaker_registry.get_or_create("elasticsearch", _FAST)
breaker_registry.get_or_create("mongodb", _FAST)
