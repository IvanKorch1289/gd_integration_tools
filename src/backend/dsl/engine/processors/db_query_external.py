"""Wave 6.2 — DSL-процессор для произвольного SQL во внешних БД.

Использует :class:`ExternalDatabaseRegistry` (через DI-провайдер
``get_external_session_manager_provider``) для получения async-сессии
по имени профиля. Параметры запроса берутся из body / properties / headers
(управляется ``params_from``).

Безопасность:
* SQL передаётся через ``sqlalchemy.text`` с bind-параметрами;
* identifier-инъекция невозможна, т.к. динамика идёт только через
  bind-параметры (никакого f-string SQL);
* SQL проходит общий guard :func:`validate_sql`
  (``src.backend.dsl.engine.processors._sql_validation``) — multi-statement и
  DDL/privilege команды (``DROP``/``ALTER``/``TRUNCATE``/``CREATE``/``GRANT``/
  ``REVOKE``) запрещены;
* для жёстких whitelist-сценариев см. ``ExternalDatabaseService``.

Фиксация транзакции (ADR-0382):
* ``commit=None`` (default) — auto: DML коммитится, чтение — нет.
  ``create_session()`` не коммитит сам, поэтому без commit DML молча
  откатывался (тихая потеря данных);
* ``commit=True`` / ``commit=False`` — явный opt-in / opt-out.

ADR-0393 (волна 18):
* **Capability-гейт** — ``required_capability`` = ``db.read`` / ``db.write``
  (по виду запроса) + ``auth_check``. Scope — алиас внешнего профиля БД
  (тот же convention, что у ``ExternalDatabaseFacade``: ``db.read`` +
  scope=profile). Раньше capability не проверялась вовсе;
* **Лимит выборки** (``max_rows``) — ``mappings().all()`` без ограничения;
* **Audit-событие** доступа к данным (без значений данных).

Контракт DSL::

    .db_query_external(
        profile="oracle_prod",
        sql="SELECT * FROM orders WHERE id = :id",
        params_from="body",
        result_property="db_result",
    )
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors._sql_validation import (
    MAX_RESULT_ROWS,
    db_capability_for_sql,
    limit_rows,
    needs_commit,
    result_returns_rows,
    sql_statement_kind,
    validate_sql,
)
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    emit_data_access_audit,
    handle_processor_error,
)

__all__ = ("ExternalDbQueryProcessor",)


_ALLOWED_PARAM_SOURCES = {"body", "properties", "headers", "none"}

_logger = get_logger("dsl.db_query_external")


class ExternalDbQueryProcessor(BaseProcessor):
    """Выполняет произвольный SQL во внешней БД по profile-имени.

    Args:
        profile: Имя профиля внешней БД (см. ``settings.external_databases.profiles``).
        sql: SQL-запрос; bind-параметры передаются через ``:name`` синтаксис
            SQLAlchemy.
        params_from: Откуда брать словарь bind-параметров —
            ``"body"`` (default) / ``"properties"`` / ``"headers"`` / ``"none"``.
            Если ``"body"`` — ожидается dict; иначе будет передан пустой словарь.
        result_property: Ключ ``Exchange.properties``, в который записать
            результат. Также пишется в ``out_message.body``.
        fetch: Стратегия получения результата —
            ``"all"`` (default) — list[dict] всех строк;
            ``"one"`` — единственная строка как dict (или None);
            ``"scalar"`` — скалярное значение.
        commit: Режим фиксации транзакции:
            ``None`` (default) — auto: DML коммитится, чтение — нет;
            ``True`` — коммитить всегда;
            ``False`` — не коммитить никогда (явный opt-out).

    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL
    compensatable: ClassVar[bool] = True
    required_capability: ClassVar[str | None] = "db.read"

    def __init__(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool | None = None,
        max_rows: int = MAX_RESULT_ROWS,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_query_external:{profile}")
        if params_from not in _ALLOWED_PARAM_SOURCES:
            raise ValueError(
                f"params_from must be one of {sorted(_ALLOWED_PARAM_SOURCES)}, "
                f"got: {params_from!r}"
            )
        if fetch not in {"all", "one", "scalar"}:
            raise ValueError(
                f"fetch must be one of 'all'|'one'|'scalar', got: {fetch!r}"
            )
        self._profile = profile
        self._sql = sql
        self._params_from = params_from
        self._result_property = result_property
        self._fetch = fetch
        self._commit = commit
        self._max_rows = max_rows
        # ADR-0393: capability зависит от вида запроса (read / write).
        self.__dict__["required_capability"] = db_capability_for_sql(sql)
        # Если коммит — это наблюдаемый внешний эффект, помечаем как SIDE_EFFECTING.
        # Запись идёт в instance __dict__, а не перезаписывает ClassVar.
        # ADR-0382: DML по умолчанию коммитится → такой же side-effect.
        if commit is True or sql_statement_kind(sql) == "dml":
            self.__dict__["side_effect"] = SideEffectKind.SIDE_EFFECTING
            self.__dict__["compensatable"] = False

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope capability-гейта — алиас внешнего профиля БД (ADR-0393).

        Args:
            exchange: Текущий Exchange (не используется).

        Returns:
            Имя профиля внешней БД.

        """
        del exchange
        return self._profile

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет SQL-запрос на внешнем профиле БД и кладёт результат в ``result_property``."""
        from sqlalchemy import text

        from src.backend.core.di.providers import get_external_session_manager_provider

        # ADR-0393: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action=self._action()):
            return

        try:
            validate_sql(self._sql)
        except ValueError as exc:
            exchange.fail(f"SQL validation failed: {exc}")
            return

        params = self._collect_params(exchange)
        session_manager = get_external_session_manager_provider()(self._profile)

        async with session_manager.create_session() as session:
            result = await session.execute(text(self._sql), params)
            # ADR-0382: ветка по ФАКТИЧЕСКОМУ типу результата, а не по префиксу
            # SQL. ``mappings()`` у result без строк бросает
            # ResourceClosedError — раньше это съедало commit() и DML
            # молча откатывалось на выходе из create_session().
            returns_rows = result_returns_rows(result, self._sql)
            # rowcount читаем ДО commit: commit закрывает курсор, после него
            # ``result.rowcount`` может бросить ResourceClosedError.
            rowcount = getattr(result, "rowcount", -1)
            # Commit ДО материализации: данные фиксируются, даже если
            # разбор результата упадёт.
            if self._should_commit(returns_rows):
                await session.commit()
            payload = self._materialize_result(
                result, returns_rows=returns_rows, rowcount=rowcount
            )

        exchange.set_property(self._result_property, payload)
        exchange.set_out(body=payload, headers=dict(exchange.in_message.headers))

        emit_data_access_audit(
            exchange,
            event=str(self.required_capability),
            capability=str(self.required_capability),
            action=self._action(),
            target=self._profile,
        )

    def _action(self) -> str:
        """Действие capability-гейта (``read`` / ``write``)."""
        return "read" if self.required_capability == "db.read" else "write"

    def _collect_params(self, exchange: Exchange[Any]) -> dict[str, Any]:
        """Собирает bind-параметры из указанного источника."""
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

    def _should_commit(self, returns_rows: bool) -> bool:
        """Решает, фиксировать ли транзакцию.

        Args:
            returns_rows: ``result.returns_rows`` — возвращает ли результат строки.

        Returns:
            ``True`` — нужен ``session.commit()``.

        """
        if self._commit is True:
            return True
        if self._commit is False:
            return False
        return needs_commit(self._sql, returns_rows=returns_rows)

    def _materialize_result(
        self, result: Any, *, returns_rows: bool, rowcount: int = -1
    ) -> Any:
        """Конвертирует SQLAlchemy-result в привычную структуру.

        Args:
            result: Результат ``session.execute``.
            returns_rows: Возвращает ли результат строки.
            rowcount: Количество затронутых строк (для DML).

        Returns:
            Для SELECT — list[dict] / dict / scalar (по ``fetch``);
            для DML без ``RETURNING`` — ``{"rowcount": <int>}``.

        """
        if not returns_rows:
            # Result без строк: ``mappings()`` бросил бы ResourceClosedError.
            return {"rowcount": rowcount}
        match self._fetch:
            case "all":
                rows = [dict(row) for row in result.mappings().all()]
                # ADR-0393: лимит выборки (без него ``SELECT *`` вытягивал
                # в память весь результат).
                rows, truncated = limit_rows(rows, limit=self._max_rows)
                if truncated:
                    _logger.warning(
                        "db_query_external result truncated: profile=%s limit=%s",
                        self._profile,
                        self._max_rows,
                    )
                return rows
            case "one":
                row = result.mappings().first()
                return dict(row) if row is not None else None
            case "scalar":
                return result.scalar_one_or_none()
            case _:
                return None

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает round-trip DSL-спецификацию ``{"db_query_external": {...}}``."""
        spec: dict[str, Any] = {"profile": self._profile, "sql": self._sql}
        if self._params_from != "body":
            spec["params_from"] = self._params_from
        if self._result_property != "db_result":
            spec["result_property"] = self._result_property
        if self._fetch != "all":
            spec["fetch"] = self._fetch
        if self._commit is not None:
            spec["commit"] = self._commit
        return {"db_query_external": spec}
