"""DSL processor ``infra_s3`` (Sprint 170 M2 Phase 2).

S3/MinIO operations через facade_get_object_storage::

    - infra_s3_get:
        key: reports/2026.pdf
        to: body.content
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_s3_get",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["key"],
    },
    capabilities=("storage.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraS3GetProcessor(BaseProcessor):
    def __init__(self, key: str, *, to: str = "body.content") -> None:
        super().__init__(name=f"infra_s3_get:{key}")
        self.key = key
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_object_storage_class,
        )
        storage = get_object_storage_class()(context)
        content = await storage.get(self.key)
        if self.target.startswith("body."):
            field = self.target[len("body."):]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = content
        else:
            exchange.set_property(self.target, content)
