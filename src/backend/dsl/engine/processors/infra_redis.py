"""DSL processor ``infra_redis`` (Sprint 170 M2 Phase 2).

Redis operations через facade_get_redis_client::

    - infra_redis_get:
        key: cache:user:42
        to: body.value
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_redis_get",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["key"],
    },
    capabilities=("cache.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraRedisGetProcessor(BaseProcessor):
    def __init__(self, key: str, *, to: str = "body.value") -> None:
        super().__init__(name=f"infra_redis_get:{key}")
        self.key = key
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_redis_client_class,
        )
        client = get_redis_client_class()(context)
        value = await client.get(self.key)
        self.set_result(exchange, self.target, value)
