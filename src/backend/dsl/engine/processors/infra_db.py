"""DSL processor ``infra_db`` (Sprint 170 M2 Phase 2).

SQL query через facade session manager::

    - infra_db_query:
        sql: "SELECT * FROM users WHERE id = :id"
        to: body.result
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_db_query",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["sql"],
    },
    capabilities=("db.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraDbQueryProcessor(BaseProcessor):
    def __init__(self, sql: str, *, to: str = "body.result") -> None:
        super().__init__(name="infra_db_query")
        self.sql = sql
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_main_session_manager_getter,
        )
        sm = get_main_session_manager_getter()()
        async with sm.session() as session:
            result = await session.execute(self.sql)
            rows = [dict(r) for r in result]
        if self.target.startswith("body."):
            field = self.target[len("body."):]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = rows
        else:
            exchange.set_property(self.target, rows)
