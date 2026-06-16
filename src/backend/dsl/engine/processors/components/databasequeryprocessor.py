"""S65 W1 — DatabaseQueryProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class DatabaseQueryProcessor(BaseProcessor):
    """Camel JDBC Component — query/execute SQL from DSL pipeline.

    Uses the application's async database engine.
    """

    def __init__(
        self,
        sql: str,
        *,
        params_from_body: bool = True,
        result_property: str = "db_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_query:{sql[:30]}")
        self._sql = sql
        self._params_from_body = params_from_body
        self._result_property = result_property

    _FORBIDDEN_SQL = {"DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"}

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands."""
        stripped = sql.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("Multi-statement SQL is not allowed")
        first_word = stripped.split()[0].upper() if stripped else ""
        if first_word in DatabaseQueryProcessor._FORBIDDEN_SQL:
            raise ValueError(f"SQL command '{first_word}' is not allowed")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from sqlalchemy import text

        from src.backend.infrastructure.database.database import get_db_manager

        try:
            self._validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params = {}
        if self._params_from_body:
            body = exchange.in_message.body
            if isinstance(body, dict):
                params = body

        try:
            db = get_db_manager()
            engine = db.get_async_engine()
            async with engine.connect() as conn:
                result = await conn.execute(text(self._sql), params)

                if self._sql.strip().upper().startswith("SELECT"):
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    exchange.set_property(self._result_property, rows)
                    exchange.set_out(
                        body=rows, headers=dict(exchange.in_message.headers)
                    )
                else:
                    await conn.commit()
                    exchange.set_property(
                        self._result_property, {"rowcount": result.rowcount}
                    )

        except Exception as exc:
            exchange.fail(f"Database query failed: {exc}")
