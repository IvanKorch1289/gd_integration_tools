"""DSL processor ``infra_mongodb_find`` (Sprint 170 M2 Phase 3).

MongoDB document queries через facade::

    - infra_mongodb_find:
        collection: users
        query:
          active: true
        to: body.users
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_mongodb_find",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "collection": {"type": "string"},
            "query": {"type": "object"},
            "to": {"type": "string"},
        },
        "required": ["collection"],
    },
    capabilities=("db.read.mongodb",),
    meta={"tier": 1, "category": "infra"},
)
class InfraMongoDBFindProcessor(BaseProcessor):
    def __init__(self, collection: str, query: dict[str, Any] | None = None, *, to: str = "body.result") -> None:
        super().__init__(name=f"infra_mongodb_find:{collection}")
        self.collection = collection
        self.query = query or {}
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_mongodb_client_class,
        )
        client = get_mongodb_client_class()(context)
        coll = client[self.collection]
        docs = await coll.find(self.query)
        if self.target.startswith("body."):
            field = self.target[len("body."):]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = docs
        else:
            exchange.set_property(self.target, docs)
