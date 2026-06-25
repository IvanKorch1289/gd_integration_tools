"""DSL processor ``facade_get_health`` (Sprint 170 M2 Phase 2).

Generic health probe через facade. Вызывает health_check любого
инфраструктурного компонента, зарегистрированного в HealthAggregator::

    - facade_get_health:
        name: redis
        to: body.health
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "facade_get_health",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["name"],
    },
    capabilities=("health.read",),
    meta={"tier": 1, "category": "infra"},
)
class FacadeGetHealthProcessor(BaseProcessor):
    def __init__(self, name: str, *, to: str = "body.health") -> None:
        super().__init__(name=f"facade_get_health:{name}")
        self.component_name = name
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_health_check_factory,
        )
        health_fn = get_health_check_factory()(self.component_name)
        result = await health_fn()
        self.set_result(exchange, self.target, result)
