"""K3 S5 W8 — DSL-процессор ``db_call_procedure``: вызов stored procedure.

Wave ``[wave:s5/k3-w8-db-call-procedure]``.

Выполняет stored procedure в БД через профиль из ``ExternalDatabaseRegistry``
(asyncpg-совместимый). Поддерживает:

* любую СУБД, в которой Procedure вызывается через ``CALL <schema>.<name>(...)``
  (PostgreSQL 11+, MS SQL ``EXEC``, Oracle ``BEGIN .. END``);
* передачу параметров из body / properties / headers (как в
  :class:`ExternalDbQueryProcessor`);
* возврат result-set через RETURNS / OUT-параметры.

Контракт DSL::

    .db_call_procedure(
        profile="oracle_prod",
        name="recalc_credit_score",
        params_from="body",
        schema="public",
        result_property="sp_result",
    )

Feature flag: ``feature_flags.db_call_procedure_enabled`` (default-OFF).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("DbCallProcedureProcessor",)


_logger = logging.getLogger("dsl.processors.db_call_procedure")
_ALLOWED_PARAM_SOURCES = frozenset({"body", "properties", "headers", "none"})


@processor(
    "db_call_procedure",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "profile": {"type": "string"},
            "name": {"type": "string"},
            "schema": {"type": "string"},
            "params_from": {"type": "string", "enum": sorted(_ALLOWED_PARAM_SOURCES)},
            "result_property": {"type": "string"},
            "dialect": {"type": "string", "enum": ["postgres", "mssql", "oracle"]},
        },
        "required": ["profile", "name"],
    },
    capabilities=("db.execute_procedure.*",),
    meta={"tier": 1, "category": "integration"},
    tags=("db", "stored-procedure", "execute"),
)
class DbCallProcedureProcessor(BaseProcessor):
    """Вызов stored procedure через профиль ExternalDatabase.

    Args:
        profile: Имя профиля внешней БД.
        name: Имя процедуры (без schema-префикса; schema передаётся отдельно).
        schema: Schema-префикс (default ``public``).
        params_from: Источник параметров — ``body`` / ``properties`` / ``headers`` / ``none``.
        result_property: Куда положить результат.
        dialect: Диалект CALL: ``postgres`` (CALL), ``mssql`` (EXEC), ``oracle`` (BEGIN..END).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        profile: str,
        name: str,
        *,
        schema: str = "public",
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str = "postgres",
        proc_name: str | None = None,
    ) -> None:
        super().__init__(name=proc_name or f"db_call_procedure:{schema}.{name}")
        if not profile:
            raise ValueError("db_call_procedure: profile must be non-empty")
        if not name:
            raise ValueError("db_call_procedure: name must be non-empty")
        if params_from not in _ALLOWED_PARAM_SOURCES:
            raise ValueError(
                f"db_call_procedure: params_from must be one of {sorted(_ALLOWED_PARAM_SOURCES)}"
            )
        if dialect not in {"postgres", "mssql", "oracle"}:
            raise ValueError(
                "db_call_procedure: dialect must be 'postgres'|'mssql'|'oracle'"
            )
        self._profile = profile
        self._sp_name = name
        self._schema = schema
        self._params_from = params_from
        self._result_property = result_property
        self._dialect = dialect

    def _build_call_sql(self, params: dict[str, Any]) -> str:
        """Строит SQL для вызова процедуры с bind-параметрами ``:name``."""
        binds = ", ".join(f":{key}" for key in params) if params else ""
        full_name = f"{self._schema}.{self._sp_name}"
        match self._dialect:
            case "postgres":
                return f"CALL {full_name}({binds})"
            case "mssql":
                return f"EXEC {full_name} {binds}"
            case "oracle":
                return f"BEGIN {full_name}({binds}); END;"
            case _:
                return f"CALL {full_name}({binds})"

    def _collect_params(self, exchange: "Exchange[Any]") -> dict[str, Any]:
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
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.db_call_procedure_enabled:
                exchange.set_property("db_call_procedure_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            pass

        from sqlalchemy import text

        from src.backend.core.di.providers import get_external_session_manager_provider

        params = self._collect_params(exchange)
        sql = self._build_call_sql(params)

        session_manager = get_external_session_manager_provider()(self._profile)
        async with session_manager.create_session() as session:
            result = await session.execute(text(sql), params)
            try:
                rows = result.mappings().all()
                payload: Any = [dict(r) for r in rows]
            except Exception:  # noqa: BLE001
                payload = None
            await session.commit()

        exchange.set_property(self._result_property, payload)
        exchange.set_out(body=payload, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"profile": self._profile, "name": self._sp_name}
        if self._schema != "public":
            spec["schema"] = self._schema
        if self._params_from != "body":
            spec["params_from"] = self._params_from
        if self._result_property != "sp_result":
            spec["result_property"] = self._result_property
        if self._dialect != "postgres":
            spec["dialect"] = self._dialect
        return {"db_call_procedure": spec}
