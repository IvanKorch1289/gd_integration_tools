"""S65 W1 — DatabaseQueryProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors._sql_validation import (
    FORBIDDEN_SQL,
    validate_sql,
)
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
        params: dict[str, Any] | None = None,
        result_property: str = "db_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_query:{sql[:30]}")
        self._sql = sql
        self._params_from_body = params_from_body
        # Cycle 172 (CRITICAL-08): явные bind-параметры. Раньше процессор
        # умел брать параметры только из тела exchange, поэтому
        # ``DbCrudProcessor`` — который строит ``:column``-плейсхолдеры —
        # выбрасывал сгенерированные параметры и получал StatementError.
        # Явные params имеют приоритет над телом exchange.
        self._params = dict(params) if params is not None else None
        self._result_property = result_property

    _FORBIDDEN_SQL = FORBIDDEN_SQL

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands.

        Delegated в общий helper (Wave 13/Q13) — канонизация копий
        ``_validate_sql`` из ``jdbc_query`` / ``databasequeryprocessor`` /
        ``infra_db`` в один модуль.
        """
        validate_sql(sql)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет параметризованный SQL-запрос с валидацией и пишет результат в exchange."""
        from sqlalchemy import text

        # S86 M2-#11 accelerated batch: DI provider.
        from src.backend.core.di.providers.cache import get_db_manager_provider

        get_db_manager = get_db_manager_provider()

        try:
            self._validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params: dict[str, Any] = {}
        if self._params is not None:
            params = self._params
        elif self._params_from_body:
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
