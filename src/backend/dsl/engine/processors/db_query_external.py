"""Wave 6.2 — DSL-процессор для произвольного SQL во внешних БД.

Использует :class:`ExternalDatabaseRegistry` (через DI-провайдер
``get_external_session_manager_provider``) для получения async-сессии
по имени профиля. Параметры запроса берутся из body / properties / headers
(управляется ``params_from``).

Безопасность:
* SQL передаётся через ``sqlalchemy.text`` с bind-параметрами;
* identifier-инъекция невозможна, т.к. динамика идёт только через
  bind-параметры (никакого f-string SQL);
* для жёстких whitelist-сценариев см. ``ExternalDatabaseService``.

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

from src.core.types.side_effect import SideEffectKind
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("ExternalDbQueryProcessor",)


_ALLOWED_PARAM_SOURCES = {"body", "properties", "headers", "none"}


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
        commit: Если ``True`` — выполнить ``session.commit()`` после запроса
            (для INSERT/UPDATE/DELETE/CALL). Default ``False``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
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
        # Если коммит — это наблюдаемый внешний эффект, помечаем как SIDE_EFFECTING.
        # Запись идёт в instance __dict__, а не перезаписывает ClassVar.
        if commit:
            self.__dict__["side_effect"] = SideEffectKind.SIDE_EFFECTING
            self.__dict__["compensatable"] = False

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет SQL-запрос на внешнем профиле БД и кладёт результат в ``result_property``."""
        from sqlalchemy import text

        from src.core.di.providers import get_external_session_manager_provider

        params = self._collect_params(exchange)
        session_manager = get_external_session_manager_provider()(self._profile)

        async with session_manager.create_session() as session:
            result = await session.execute(text(self._sql), params)
            payload = self._materialize_result(result)
            if self._commit:
                await session.commit()

        exchange.set_property(self._result_property, payload)
        exchange.set_out(body=payload, headers=dict(exchange.in_message.headers))

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

    def _materialize_result(self, result: Any) -> Any:
        """Конвертирует SQLAlchemy-result в привычную структуру."""
        match self._fetch:
            case "all":
                rows = result.mappings().all()
                return [dict(row) for row in rows]
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
        if self._commit is not False:
            spec["commit"] = self._commit
        return {"db_query_external": spec}
