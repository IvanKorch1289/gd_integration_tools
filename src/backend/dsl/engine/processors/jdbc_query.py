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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import text

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    pass


__all__ = ("JdbcQueryProcessor",)


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

    _FORBIDDEN_SQL: ClassVar[frozenset[str]] = frozenset(
        {"DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"}
    )

    def __init__(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
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

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Block dangerous SQL: multi-statement, DDL, privilege commands."""
        stripped = sql.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("Multi-statement SQL is not allowed")
        first_word = stripped.split()[0].upper() if stripped else ""
        if first_word in JdbcQueryProcessor._FORBIDDEN_SQL:
            raise ValueError(f"SQL command '{first_word}' is not allowed")

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

        try:
            self._validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params = self._collect_params(exchange)
        session_manager = get_external_session_manager_provider()(self._profile)

        async with session_manager.create_session() as session:
            result = await session.execute(text(self._sql), params)

            sql_upper = self._sql.strip().upper()
            is_select = sql_upper.startswith("SELECT")

            if is_select:
                rows = [dict(row._mapping) for row in result.fetchall()]
                exchange.set_property(self._result_property, rows)
                exchange.set_out(body=rows, headers=dict(exchange.in_message.headers))
            else:
                await session.commit()
                affected_count = result.rowcount
                exchange.set_property(self._result_property, affected_count)
                exchange.set_out(
                    body={"affected_count": affected_count},
                    headers=dict(exchange.in_message.headers),
                )

    def to_spec(self) -> dict[str, Any] | None:
        """Return round-trip DSL spec ``{"jdbc_query": {...}}``."""
        spec: dict[str, Any] = {"profile": self._profile, "sql": self._sql}
        if self._params_from != "body":
            spec["params_from"] = self._params_from
        if self._result_property != "jdbc_result":
            spec["result_property"] = self._result_property
        return {"jdbc_query": spec}
