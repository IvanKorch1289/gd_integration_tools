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

NOTE (capability-барьер): ``required_capability`` намеренно **не** задан.
Capability-путь (``BaseProcessor.auth_check`` → ``AuthorizationFacade`` →
Casbin/OPA) сейчас deny-all в проде (in-memory policies пусты, sync-хуков
нет) → любой ``required_capability`` сделал бы шаг недоступным для всех.
Capability-барьер — отдельная ADR-задача; декларация
``capabilities=("db.read",)`` в реестре процессоров остаётся метаданными.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors._sql_validation import (
    needs_commit,
    result_returns_rows,
    validate_sql,
)
from src.backend.dsl.engine.processors.base import BaseProcessor
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

    def __init__(
        self, sql: str, *, to: str = "body.result", params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(name="infra_db_query")
        self.sql = sql
        self.target = to
        self._params: dict[str, Any] = dict(params) if params else {}

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
            else:
                rows = [{"rowcount": rowcount}]
        self.set_result(exchange, self.target, rows)
