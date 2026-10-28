"""DSL processor ``infra_clickhouse_query`` (Sprint 170 M2 Phase 3).

ClickHouse analytical queries через facade::

    - infra_clickhouse_query:
        sql: "SELECT count() FROM events WHERE ts > now() - 3600"
        to: body.result

SQL проходит канонический guard: multi-statement и DDL/privilege-команды
запрещены.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors._sql_validation import validate_sql
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_clickhouse_query",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {"sql": {"type": "string"}, "to": {"type": "string"}},
        "required": ["sql"],
    },
    capabilities=("analytics.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraClickHouseQueryProcessor(BaseProcessor):
    """Метод InfraClickHouseQueryProcessor (см. signature)."""

    def __init__(self, sql: str, *, to: str = "body.result") -> None:
        super().__init__(name="infra_clickhouse_query")
        self.sql = sql
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет валидированный SQL-запрос к ClickHouse."""
        try:
            validate_sql(self.sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        from src.backend.core.di.providers.infrastructure_locator import (
            get_clickhouse_client_class,
        )

        client = get_clickhouse_client_class()(context)  # type: ignore[arg-type]
        result = await client.query(self.sql)
        self.set_result(exchange, self.target, result)
