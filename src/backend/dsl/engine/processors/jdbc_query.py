"""GAP-INT-1 S35 — JDBC Query Processor for arbitrary SQL against external JDBC-compatible DBs.

Executes arbitrary SQL (SELECT / INSERT / UPDATE / DELETE) against an external
database profile from ``ExternalDatabaseRegistry``. Similar to
:class:`DatabaseQueryProcessor` but for external JDBC targets.

Security:
* SQL is validated: DDL, DROP, GRANT, REVOKE and multi-statement are blocked.
* Bind-parameters are passed via SQLAlchemy ``text()`` (no f-string injection).

DSL contract::

    .jdbc_query(
        profile="oracle_prod",
        sql="SELECT * FROM orders WHERE customer_id = :cid",
        params_from="body",
        result_property="jdbc_result",
    )

SELECT → sets ``exchange.properties[result_property]`` to list[dict]
INSERT/UPDATE/DELETE → sets ``exchange.properties[result_property]`` to int (affected count)

ADR-0393 (волна 18): capability-гейт (``db.read`` / ``db.write``, scope —
алиас профиля внешней БД), лимит выборки (``max_rows``) и audit-событие
доступа к данным (без значений данных).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import text

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors._sql_validation import (
    FORBIDDEN_SQL,
    MAX_RESULT_ROWS,
    db_capability_for_sql,
    limit_rows,
    needs_commit,
    result_returns_rows,
    validate_sql,
)
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    emit_data_access_audit,
    handle_processor_error,
)

if TYPE_CHECKING:
    pass


__all__ = ("JdbcQueryProcessor",)

_logger = get_logger("dsl.jdbc_query")


class JdbcQueryProcessor(BaseProcessor):
    """Arbitrary SQL executor against an external JDBC-compatible database profile.

    Args:
        sql: SQL query string with bind-parameters using ``:name`` syntax.
        profile: Name of the external database profile from
            ``ExternalDatabaseRegistry``.
        params_from: Source of bind-parameters —
            ``"body"`` (default) / ``"properties"`` / ``"headers"`` / ``"none"``.
        result_property: Exchange property key where the result is stored.
            For SELECT: list[dict]. For INSERT/UPDATE/DELETE: int (affected count).
        name: Optional processor name for logging/debugging.

    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL
    compensatable: ClassVar[bool] = True
    required_capability: ClassVar[str | None] = "db.read"

    _FORBIDDEN_SQL: ClassVar[frozenset[str]] = FORBIDDEN_SQL

    def __init__(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
        max_rows: int = MAX_RESULT_ROWS,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"jdbc_query:{sql[:30]}")
        if not profile:
            raise ValueError("jdbc_query: profile must be non-empty")
        if not sql:
            raise ValueError("jdbc_query: sql must be non-empty")
        self._sql = sql
        self._profile = profile
        self._params_from = params_from
        self._result_property = result_property
        self._max_rows = max_rows
        # ADR-0393: capability зависит от вида запроса (read / write).
        self.__dict__["required_capability"] = db_capability_for_sql(sql)

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope capability-гейта — алиас внешнего профиля БД (ADR-0393).

        Args:
            exchange: Текущий Exchange (не используется).

        Returns:
            Имя профиля внешней БД.

        """
        del exchange
        return self._profile

    def _action(self) -> str:
        """Действие capability-гейта (``read`` / ``write``)."""
        return "read" if self.required_capability == "db.read" else "write"

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands.

        Delegated в общий helper (Wave 13/Q13) — канонизация копий
        ``_validate_sql`` из ``jdbc_query`` / ``databasequeryprocessor`` /
        ``infra_db`` в один модуль.
        """
        validate_sql(sql)

    def _collect_params(self, exchange: Exchange[Any]) -> dict[str, Any]:
        """Collect bind-parameters from the configured source."""
        match self._params_from:
            case "body":
                body = exchange.in_message.body
                return dict(body) if isinstance(body, dict) else {}
            case "properties":
                return dict(exchange.properties)
            case "headers":
                return dict(exchange.in_message.headers)
            case "none":
                return {}
            case _:
                return {}

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Execute SQL against the external database profile and set result property."""
        from src.backend.core.di.providers import get_external_session_manager_provider

        # ADR-0393: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action=self._action()):
            return

        try:
            self._validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params = self._collect_params(exchange)
        session_manager = get_external_session_manager_provider()(self._profile)

        async with session_manager.create_session() as session:
            result = await session.execute(text(self._sql), params)

            # ADR-0382: SELECT-детект по фактическому типу результата
            # (``returns_rows``), а не по префиксу SQL: ``WITH ... SELECT``
            # раньше уходил в ветку DML → ``{"rowcount": -1}`` и строки
            # терялись.
            returns_rows = result_returns_rows(result, self._sql)
            rowcount = getattr(result, "rowcount", -1)
            if needs_commit(self._sql, returns_rows=returns_rows):
                await session.commit()

            if returns_rows:
                rows = [dict(row._mapping) for row in result.fetchall()]
                # ADR-0393: лимит выборки.
                rows, truncated = limit_rows(rows, limit=self._max_rows)
                if truncated:
                    _logger.warning(
                        "jdbc_query result truncated: profile=%s limit=%s",
                        self._profile,
                        self._max_rows,
                    )
                exchange.set_property(self._result_property, rows)
                exchange.set_out(body=rows, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property(self._result_property, rowcount)
                exchange.set_out(
                    body={"affected_count": rowcount},
                    headers=dict(exchange.in_message.headers),
                )

        emit_data_access_audit(
            exchange,
            event=str(self.required_capability),
            capability=str(self.required_capability),
            action=self._action(),
            target=self._profile,
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Return round-trip DSL spec ``{"jdbc_query": {...}}``."""
        spec: dict[str, Any] = {"profile": self._profile, "sql": self._sql}
        if self._params_from != "body":
            spec["params_from"] = self._params_from
        if self._result_property != "jdbc_result":
            spec["result_property"] = self._result_property
        return {"jdbc_query": spec}
