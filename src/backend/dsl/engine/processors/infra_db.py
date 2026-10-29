"""DSL processor ``infra_db`` (Sprint 170 M2 Phase 2) — fail-closed (Wave 13 / Q13).

SQL query к ВНУТРЕННЕЙ БД через инфраструктурный facade session manager::

    - infra_db_query:
        sql: "SELECT * FROM users WHERE id = :id"
        params: {id: 42}
        to: body.result

Security (Wave 13 / Q13, аудит S-27 — критическая находка):

* **feature-flag, default-OFF** — ``feature_flags.infra_db_query_enabled``.
  Произвольный SQL к внутренней БД — тот же класс риска, что и отключённый
  ``script_runner`` (произвольное исполнение). Пока флаг выключен, шаг
  fail-closed: ``exchange.fail(...)`` + error-лог, SQL **не** исполняется
  (в отличие от ``db_call_procedure``, который при выключенном флаге
  молча помечает шаг как ``skipped``).
* **SQL-валидация** — общий helper
  :func:`src.backend.dsl.engine.processors._sql_validation.validate_sql`:
  multi-statement и ``DROP/ALTER/TRUNCATE/CREATE/GRANT/REVOKE`` запрещены.
* **bind-параметры** — запрос уходит в БД как ``text(sql)`` + ``params``
  (без конкатенации значений). Раньше шаг передавал «сырую» строку в
  ``session.execute()`` → SQLAlchemy 2.x бросал ``ObjectNotExecutableError``,
  то есть шаг был нерабочим в рантайме.

Результат: ``SELECT`` → ``list[dict]`` в ``to``-target; DML → коммит и
``[{"rowcount": <int>}]`` в ``to``-target.

NOTE (ADR-0393, волна 18): capability-барьер больше не «отложен на
потом» — ``required_capability`` задан (``db.read`` / ``db.write``), а
enforcement включается флагом ``dsl_capability_gate_enabled`` (ADR-0366),
который в prod/staging включён явно. Scope — алиас таблицы из SQL.
Также добавлены лимит выборки (``max_rows``) и audit-событие доступа
к данным (без значений данных).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors._sql_validation import (
    MAX_RESULT_ROWS,
    db_capability_for_sql,
    limit_rows,
    needs_commit,
    result_returns_rows,
    sql_capability_scope,
    validate_sql,
)
from src.backend.dsl.engine.processors.base import BaseProcessor, emit_data_access_audit
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("InfraDbQueryProcessor",)

_logger = get_logger("dsl.processors.infra_db")


@processor(
    "infra_db_query",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string"},
            "params": {"type": "object"},
            "to": {"type": "string"},
        },
        "required": ["sql"],
    },
    capabilities=("db.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraDbQueryProcessor(BaseProcessor):
    """Произвольный SQL к внутренней БД — за feature-флагом (default-OFF).

    Args:
        sql: SQL-запрос с bind-плейсхолдерами ``:name``.
        to: Куда положить результат (``body.result`` по умолчанию).
        params: Bind-параметры для ``:name``-плейсхолдеров.

    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL
    compensatable: ClassVar[bool] = False
    required_capability: ClassVar[str | None] = "db.read"

    def __init__(
        self,
        sql: str,
        *,
        to: str = "body.result",
        params: dict[str, Any] | None = None,
        max_rows: int = MAX_RESULT_ROWS,
    ) -> None:
        super().__init__(name="infra_db_query")
        self.sql = sql
        self.target = to
        self._params: dict[str, Any] = dict(params) if params else {}
        self._max_rows = max_rows
        # ADR-0393: capability зависит от вида запроса (read / write).
        self.__dict__["required_capability"] = db_capability_for_sql(sql)

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope capability-гейта — алиас таблицы из SQL (ADR-0393).

        Args:
            exchange: Текущий Exchange (не используется).

        Returns:
            Имя таблицы из SQL либо ``None``.

        """
        del exchange
        return sql_capability_scope(self.sql)

    def _action(self) -> str:
        """Действие capability-гейта (``read`` / ``write``)."""
        return "read" if self.required_capability == "db.read" else "write"

    @staticmethod
    def _flag_enabled() -> bool:
        """Читает feature-flag ``infra_db_query_enabled`` (fail-closed).

        Returns:
            ``True`` только если флаг явно включён. Любая ошибка чтения
            (нет модуля, нет атрибута) трактуется как «выключено» —
            шаг остаётся fail-closed.

        """
        try:
            from src.backend.core.config.features import feature_flags
        except (ImportError, AttributeError, RuntimeError) as exc:
            _logger.error("infra_db_query.flag_unavailable: %s", exc)
            return False
        return bool(getattr(feature_flags, "infra_db_query_enabled", False))

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Приводит строку результата к dict (совместимо с SQLAlchemy ``Row``)."""
        mapping = getattr(row, "_mapping", None)
        if mapping is not None:
            return dict(mapping)
        return dict(row)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Исполняет SQL (если флаг включён и SQL прошёл валидацию).

        Args:
            exchange: Текущий Exchange.
            context: Контекст исполнения DSL-маршрута.

        """
        if not self._flag_enabled():
            _logger.error(
                "infra_db_query disabled by feature flag "
                "'infra_db_query_enabled' (Wave 13/Q13, S-27): SQL не исполняется"
            )
            exchange.fail(
                "infra_db_query is disabled: feature flag "
                "'infra_db_query_enabled' is OFF (arbitrary SQL against the "
                "internal DB is disabled by default — see Wave 13/Q13, S-27)"
            )
            return

        try:
            validate_sql(self.sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        # ADR-0393: capability-гейт (после feature-флага: выключенный флаг
        # даёт более понятную ошибку, чем отказ capability).
        if not await self.auth_check(exchange, action=self._action()):
            return

        from sqlalchemy import text

        from src.backend.core.di.providers.infrastructure_locator import (
            get_main_session_manager_getter,
        )

        session_manager = get_main_session_manager_getter()()
        async with session_manager.create_session() as session:
            result = await session.execute(text(self.sql), self._params)
            # ADR-0382: SELECT-детект по фактическому типу результата, а не по
            # первой букве SQL — ``WITH ... SELECT`` больше не считается DML.
            returns_rows = result_returns_rows(result, self.sql)
            rowcount = getattr(result, "rowcount", -1)
            if needs_commit(self.sql, returns_rows=returns_rows):
                await session.commit()
            if returns_rows:
                rows = [self._row_to_dict(row) for row in result]
                # ADR-0393: лимит выборки.
                rows, truncated = limit_rows(rows, limit=self._max_rows)
                if truncated:
                    _logger.warning(
                        "infra_db_query result truncated: limit=%s", self._max_rows
                    )
            else:
                rows = [{"rowcount": rowcount}]
        self.set_result(exchange, self.target, rows)

        emit_data_access_audit(
            exchange,
            event=str(self.required_capability),
            capability=str(self.required_capability),
            action=self._action(),
            target=self._capability_scope(exchange) or "internal",
        )
