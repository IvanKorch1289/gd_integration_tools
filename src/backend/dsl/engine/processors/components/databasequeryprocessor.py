"""S65 W1 — DatabaseQueryProcessor extracted from components.py.

Per-processor file split.

ADR-0393 (волна 18) — что закрывает этот модуль:

* **Capability-гейт.** ``required_capability`` = ``db.read`` / ``db.write``
  (по виду запроса) + ``auth_check`` → runtime-резолвер (ADR-0366).
  Раньше шаг вообще не проверял capability: любой DSL-роут читал и писал
  любую БД;
* **Tenant-скоуп.** Шаг ходит в БД через Core ``Connection``
  (``engine.connect()``), то есть **мимо** ORM-фильтра и raw-SQL guard'а
  сессии. Поэтому перед выполнением вызывается тот же fail-closed guard
  (:func:`src.backend.core.tenancy.sqlalchemy_filter.guard_raw_sql_for_tenant`):
  обращение к tenant-aware таблице без явного ``tenant_id``-предиката
  отклоняется;
* **Лимит выборки** (``max_rows``) — ``fetchall()`` без ограничения
  вытягивал в память весь результат;
* **Audit-событие** доступа к данным (без значений данных).
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors._sql_validation import (
    FORBIDDEN_SQL,
    MAX_RESULT_ROWS,
    db_capability_for_sql,
    limit_rows,
    needs_commit,
    result_returns_rows,
    sql_capability_scope,
    validate_sql,
)
from src.backend.dsl.engine.processors.base import BaseProcessor, emit_data_access_audit

_comp_logger = get_logger("dsl.components")


class DatabaseQueryProcessor(BaseProcessor):
    """Camel JDBC Component — query/execute SQL from DSL pipeline.

    Uses the application's async database engine.

    Args:
        sql: SQL-запрос (bind-параметры — ``:name``).
        params_from_body: Брать bind-параметры из тела exchange.
        params: Явные bind-параметры (приоритетнее тела).
        result_property: Ключ ``Exchange.properties`` для результата.
        capability_scope: Явный scope capability-гейта (алиас ресурса).
            ``None`` — выводится из SQL (имя таблицы).
        max_rows: Максимум строк в результате (``<= 0`` — без ограничения).
        name: Имя процессора.

    """

    required_capability: ClassVar[str | None] = "db.read"

    def __init__(
        self,
        sql: str,
        *,
        params_from_body: bool = True,
        params: dict[str, Any] | None = None,
        result_property: str = "db_result",
        capability_scope: str | None = None,
        max_rows: int = MAX_RESULT_ROWS,
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
        self._scope_override = capability_scope
        self._max_rows = max_rows
        # ADR-0393: capability зависит от вида запроса (read / write).
        self.__dict__["required_capability"] = db_capability_for_sql(sql)

    _FORBIDDEN_SQL = FORBIDDEN_SQL

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands.

        Delegated в общий helper (Wave 13/Q13) — канонизация копий
        ``_validate_sql`` из ``jdbc_query`` / ``databasequeryprocessor`` /
        ``infra_db`` в один модуль.
        """
        validate_sql(sql)

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope capability-гейта — алиас ресурса (таблица).

        Args:
            exchange: Текущий Exchange (не используется).

        Returns:
            Явный scope, если задан; иначе — имя таблицы из SQL.

        """
        if self._scope_override is not None:
            return self._scope_override
        return sql_capability_scope(self._sql)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет параметризованный SQL-запрос с валидацией и пишет результат в exchange."""
        from sqlalchemy import text

        # S86 M2-#11 accelerated batch: DI provider.
        from src.backend.core.di.providers.cache import get_db_manager_provider

        get_db_manager = get_db_manager_provider()

        # ADR-0393: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action=self._action()):
            return

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

        scope = self._capability_scope(exchange)
        capability = str(self.required_capability)

        try:
            db = get_db_manager()
            engine = db.get_async_engine()
            async with engine.connect() as conn:
                # ADR-0393: tenant-guard для Core-пути (мимо ORM-фильтра).
                self._guard_tenant_scope(exchange, conn, params)
                result = await conn.execute(text(self._sql), params)

                # ADR-0382: тип результата определяется по факту
                # (``result.returns_rows``), а не по первой букве SQL.
                # ``WITH ... SELECT`` раньше считался DML → ``{"rowcount": -1}``
                # и строки терялись.
                returns_rows = result_returns_rows(result, self._sql)
                rowcount = getattr(result, "rowcount", -1)
                if needs_commit(self._sql, returns_rows=returns_rows):
                    await conn.commit()

                if returns_rows:
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    rows, truncated = limit_rows(rows, limit=self._max_rows)
                    if truncated:
                        _comp_logger.warning(
                            "db_query result truncated: limit=%s rows=%s",
                            self._max_rows,
                            len(rows),
                        )
                    exchange.set_property(self._result_property, rows)
                    exchange.set_out(
                        body=rows, headers=dict(exchange.in_message.headers)
                    )
                else:
                    exchange.set_property(self._result_property, {"rowcount": rowcount})

        except Exception as exc:
            exchange.fail(f"Database query failed: {exc}")
            return

        emit_data_access_audit(
            exchange,
            event=str(self.required_capability),
            capability=capability,
            action=self._action(),
            target=scope or "internal",
        )

    def _action(self) -> str:
        """Действие capability-гейта (``read`` / ``write``)."""
        return "read" if self.required_capability == "db.read" else "write"

    def _guard_tenant_scope(
        self, exchange: Exchange[Any], conn: Any, params: dict[str, Any]
    ) -> None:
        """Fail-closed tenant-guard для Core-вызова (ADR-0393).

        Core ``Connection`` не проходит через session-level ``do_orm_execute``,
        поэтому ORM-фильтр и raw-SQL guard к нему неприменимы. Здесь
        применяется тот же канон: обращение к tenant-aware таблице обязано
        содержать явный ``tenant_id``-предикат, иначе — отказ.

        Args:
            exchange: Текущий Exchange (источник tenant-контекста).
            conn: Соединение SQLAlchemy.
            params: Bind-параметры запроса.

        Raises:
            TenantIsolationError: Если tenant-предиката нет.

        """
        from src.backend.core.tenancy import get_tenant_id
        from src.backend.core.tenancy.sqlalchemy_filter import guard_raw_sql

        guard_raw_sql(self._sql, params, get_tenant_id(), connection=conn)
