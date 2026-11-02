# ruff: noqa: S608 — false positive (controlled pattern)
# bandit: noqa: B608 — false positive (controlled pattern: table name
#   from __init__ (not user input), values bound via :param placeholders)
"""Batch DB processors — INSERT / UPDATE / DELETE через SQLAlchemy core.

ADR-0418 (волна 24) — что закрывает этот модуль:

* **Capability-гейт.** ``required_capability = "db.write"`` + ``auth_check``
  (тот же канон, что у ``db_crud`` / ``db_query``). Раньше шаг писал в любую
  внешнюю БД без проверки прав;
* **Квотирование идентификаторов.** Таблица и колонки оборачиваются в
  кавычки по правилам диалекта целевой СУБД. Раньше идентификаторы
  подставлялись в SQL как есть (``f"INSERT INTO {self._table} ..."``) —
  зарезервированное слово (``order``, ``user``) давало синтаксическую
  ошибку;
* **Tenant-скоуп.** ``tenant_column`` включает обязательный tenant-скоуп
  (INSERT — значение в данных, UPDATE/DELETE — предикат). Без
  tenant-контекста шаг падает fail-closed; попытка записать чужой tenant —
  тоже отказ. Для внешних БД схема неизвестна, поэтому столбец tenant'а
  задаётся явно;
* **Лимит батча.** ``max_batch`` ограничивает число строк в одном вызове
  (``MAX_BATCH_ROWS`` по умолчанию) — иначе один шаг мог залить в БД
  миллионы строк;
* **Валидный профиль.** ``profile="default"`` больше не приводит к
  ``DatabaseError``: профиль разрешается автоматически (единственный
  сконфигурированный) либо отказ с перечнем доступных профилей.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import bindparam, text

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.core.utils.sql_identifiers import validate_identifier
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

# Канонический квотер идентификаторов — тот же, что в ``db_crud``
# (ADR-0382): кавычки по правилам диалекта целевой СУБД. Дублировать
# реализацию в третьем месте нельзя (Wave 13/Q13 — канонизация
# SQL-хелперов). Приватное имя — сознательный компромисс: оба модуля в
# одном пакете ``dsl.engine.processors``.
from src.backend.dsl.engine.processors.db_crud import _quote_identifier as _quote

_logger = get_logger("dsl.batch")

#: Максимум строк в одном batch-вызове (ADR-0418).
MAX_BATCH_ROWS: int = 1000

#: Имя профиля внешней БД, означающее «выбрать автоматически» (ADR-0418).
AUTO_PROFILE: str = "default"

#: Диалекты, для которых умеет квотить идентификаторы SQLAlchemy.
_SUPPORTED_DIALECTS: frozenset[str] = frozenset(
    {"postgresql", "sqlite", "mysql", "oracle", "mssql"}
)


def _validate_identifier(name: str) -> None:
    """Валидирует SQL-идентификатор по канону ADR-0365.

    Args:
        name: Имя колонки / alias.

    Raises:
        ValueError: Если имя не является безопасным идентификатором.

    """
    try:
        validate_identifier(name, context="batch.identifier")
    except ValueError as exc:
        raise ValueError(f"Invalid identifier: {name!r}") from exc


# lazy-evaluated at module level for testability
_get_external_db_registry = None


def _lazy_get_external_db_registry():
    global _get_external_db_registry
    if _get_external_db_registry is None:
        # S75 M2-#11 batch 10: DI provider вместо inline infrastructure import.
        from src.backend.core.di.providers.db import get_external_db_registry_provider

        _get_external_db_registry = get_external_db_registry_provider
    return _get_external_db_registry


if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = (
    "AUTO_PROFILE",
    "MAX_BATCH_ROWS",
    "BatchDeleteProcessor",
    "BatchInsertProcessor",
    "BatchUpdateProcessor",
)


def _validate_table(table: str) -> None:
    """Проверяет, что имя таблицы (schema.table или table) безопасно.

    Каждый сегмент проверяется по канону ADR-0365
    (``core.utils.sql_identifiers.validate_identifier``).

    Args:
        table: Имя таблицы.

    Raises:
        ValueError: Если имя содержит небезопасные символы.

    """
    for part in table.split("."):
        try:
            validate_identifier(part, context="batch.table")
        except ValueError as exc:
            raise ValueError(f"Invalid table name: {table!r}") from exc


def _resolve_bundle(profile: str) -> Any:
    """Получить bundle целевой БД (ADR-0418).

    ``AUTO_PROFILE`` (``"default"``) → **основная** БД приложения: это
    единственная БД, которая существует всегда. Раньше дефолт указывал на
    несуществующий профиль внешней БД, и каждый такой шаг падал с
    ``DatabaseError`` («Внешняя БД 'default' не зарегистрирована»).

    Явно заданный профиль → внешняя БД из реестра (несуществующий профиль
    даёт понятную ошибку реестра).

    Args:
        profile: Имя профиля либо ``AUTO_PROFILE``.

    Returns:
        Bundle целевой БД.

    """
    if profile == AUTO_PROFILE:
        from src.backend.core.di.providers.db import get_db_initializer_provider

        return get_db_initializer_provider().as_bundle()
    return _lazy_get_external_db_registry()().get_bundle(profile)


def _dialect_of(bundle: Any) -> str:
    """Диалект целевой СУБД — для квотирования идентификаторов (ADR-0382).

    Args:
        bundle: Bundle внешней БД (его ``settings.type`` — тип СУБД).

    Returns:
        Имя диалекта SQLAlchemy (``postgresql`` — безопасный дефолт).

    """
    raw = getattr(getattr(bundle, "settings", None), "type", None)
    value = getattr(raw, "value", raw)
    if isinstance(value, str) and value in _SUPPORTED_DIALECTS:
        return value
    return "postgresql"


def _tenant_id_or_fail(table: str) -> str:
    """Активный tenant или fail-closed (ADR-0418).

    Args:
        table: Имя tenant-aware таблицы (для сообщения об ошибке).

    Returns:
        Идентификатор tenant'а.

    Raises:
        TenantIsolationError: Если tenant-контекст не привязан.

    """
    from src.backend.core.tenancy import get_tenant_id
    from src.backend.core.tenancy.sqlalchemy_filter import TenantIsolationError

    tenant_id = get_tenant_id()
    if not tenant_id:
        raise TenantIsolationError(
            message=(
                f"batch: таблица '{table}' — tenant-aware, но tenant-контекст "
                "не привязан (ADR-0418). Операция отклонена: tenant-скоуп "
                "неизвестен."
            )
        )
    return tenant_id


def _check_tenant_value(
    table: str, tenant_column: str, tenant_id: str, value: Any
) -> None:
    """Проверить, что указанное значение tenant'а — текущий (ADR-0418).

    Args:
        table: Имя таблицы (для сообщения об ошибке).
        tenant_column: Имя столбца tenant'а.
        tenant_id: Активный tenant.
        value: Значение из данных шага.

    Raises:
        TenantIsolationError: Если значение принадлежит другому tenant'у.

    """
    from src.backend.core.tenancy.sqlalchemy_filter import TenantIsolationError

    if value is not None and value != tenant_id:
        raise TenantIsolationError(
            message=(
                f"batch: в данных таблицы '{table}' задан чужой tenant "
                f"({tenant_column}={value!r}) — ожидается {tenant_id!r} "
                "(ADR-0418). Операция отклонена."
            )
        )


def _check_batch_size(count: int, max_batch: int) -> None:
    """Ограничить размер батча (ADR-0418).

    Args:
        count: Число строк в батче.
        max_batch: Максимум строк (``<= 0`` — без ограничения).

    Raises:
        ValueError: Если размер превышает ``max_batch``.

    """
    if max_batch > 0 and count > max_batch:
        raise ValueError(
            f"batch: размер батча {count} превышает лимит {max_batch}. "
            "Разбейте операцию на несколько шагов."
        )


def _tenant_scope(
    table: str, tenant_column: str | None, *, is_main: bool
) -> tuple[str | None, str | None]:
    """Определить tenant-скоуп (столбец + активный tenant).

    Для **основной** БД скоуп определяется автоматически по реестру
    tenant-aware таблиц (тот же канон, что у ``db_crud``): запись в
    tenant-таблицу без tenant-предиката — кросс-tenant запись.

    Для **внешней** БД схема неизвестна, поэтому столбец tenant'а задаётся
    явно (``tenant_column``).

    Args:
        table: Имя tenant-aware таблицы.
        tenant_column: Явно заданный столбец tenant'а (``None`` — авто).
        is_main: Целевая БД — основная БД приложения.

    Returns:
        Кортеж ``(tenant_column, tenant_id)``; ``(None, None)``, если
        tenant-скоуп не запрошен.

    Raises:
        ValueError: Если имя столбца некорректно.
        TenantIsolationError: Если tenant-контекст не привязан.

    """
    if tenant_column is not None:
        _validate_identifier(tenant_column)
        return tenant_column, _tenant_id_or_fail(table)
    if is_main:
        from src.backend.core.tenancy.sqlalchemy_filter import tenant_aware_tables

        if table.lower() in tenant_aware_tables():
            return "tenant_id", _tenant_id_or_fail(table)
    return None, None


class BatchInsertProcessor(BaseProcessor):
    """Batch INSERT через SQLAlchemy core.

    ADR-0418: capability-гейт (``db.write``), квотирование идентификаторов,
    tenant-скоуп, лимит размера батча, валидный профиль по умолчанию.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False
    required_capability: ClassVar[str | None] = "db.write"

    def __init__(
        self,
        *,
        table: str,
        items: list[dict[str, Any]] | None = None,
        profile: str = AUTO_PROFILE,
        max_batch: int = MAX_BATCH_ROWS,
        tenant_column: str | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализирует batch-INSERT.

        Args:
            table: Имя таблицы.
            items: Список dict для вставки (``None`` — берётся из body).
            profile: Профиль внешней БД (``"default"`` — авто-выбор).
            max_batch: Максимум строк в батче (``<= 0`` — без ограничения).
            tenant_column: Столбец tenant'а (включает tenant-скоуп).
            name: Имя процессора.

        """
        super().__init__(name=name or f"batch_insert:{table}")
        self._table = table
        self._items = items
        self._profile = profile
        self._max_batch = max_batch
        self._tenant_column = tenant_column

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет пакетную вставку (INSERT) строк в таблицу через SQLAlchemy executemany.

        Args:
            exchange: Текущий обмен со списком записей для вставки.
            context: Контекст выполнения процессора.

        """
        # ADR-0418: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action="write"):
            return

        items = self._items if self._items is not None else exchange.in_message.body
        if not isinstance(items, list) or not items:
            exchange.set_property("batch_insert_result", {"affected": 0})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
        _check_batch_size(len(items), self._max_batch)
        # fail-fast: validate all column identifiers before touching DB.
        # ADR-0382: колонки — UNION по всем items (раньше брались только из
        # 1-го item → лишние ключи остальных молча терялись).
        columns: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"batch_insert: каждый item должен быть dict, получено {type(item).__name__}"
                )
            for col in item:
                _validate_identifier(col)
                if col not in columns:
                    columns.append(col)
        if not columns:
            exchange.set_property("batch_insert_result", {"affected": 0})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))
            return

        tenant_column, tenant_id = _tenant_scope(
            self._table, self._tenant_column, is_main=self._profile == AUTO_PROFILE
        )
        if tenant_column is not None:
            for item in items:
                _check_tenant_value(
                    self._table, tenant_column, tenant_id, item.get(tenant_column)
                )
            if tenant_column not in columns:
                columns.append(tenant_column)

        bundle = _resolve_bundle(self._profile)
        dialect = _dialect_of(bundle)
        # ADR-0418: идентификаторы квотятся по правилам диалекта.
        table_sql = _quote(self._table, dialect)
        columns_sql = ", ".join(_quote(col, dialect) for col in columns)
        placeholders = ", ".join(f":{col}" for col in columns)
        stmt_text = f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders})"
        # executemany через list[dict]: все items приводятся к общему набору
        # колонок, отсутствующие значения → NULL (данные не теряются).
        rows = [{col: item.get(col) for col in columns} for item in items]
        if tenant_column is not None and tenant_id is not None:
            for row in rows:
                row[tenant_column] = tenant_id
        async with bundle.async_session_maker() as session:
            result = await session.execute(text(stmt_text), rows)
            await session.commit()
            affected = getattr(result, "rowcount", len(items))
            exchange.set_property("batch_insert_result", {"affected": affected})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        spec: dict[str, Any] = {
            "table": self._table,
            "items": self._items,
            "profile": self._profile,
        }
        if self._max_batch != MAX_BATCH_ROWS:
            spec["max_batch"] = self._max_batch
        if self._tenant_column is not None:
            spec["tenant_column"] = self._tenant_column
        return {"batch_insert": spec}


class BatchUpdateProcessor(BaseProcessor):
    """Batch UPDATE через SQLAlchemy core (executemany per column-group).

    S66 W4: docstring clarification (vs analysis P1-5 claim "один UPDATE per item").

    Реально:
    * Items группируются по ``frozenset(update_columns)`` (идентичный
      набор обновляемых колонок = один group);
    * Для каждого group: ОДИН ``UPDATE ... WHERE key = :_key`` statement,
      выполненный через ``session.execute(text(stmt), params_list)`` —
      это **executemany** pattern, SINGLE RTT per group;
    * N групп → N statements, но каждый statement = bulk UPDATE
      (НЕ цикл per item).

    Сравнение с ошибочным утверждением:
    * ~~"for item in batch: await session.execute(update_stmt, item)"~~
      (анализ P1-5, **НЕ соответствует коду**);
    * Реально: groups.items() → executemany per group.

    ADR-0418: capability-гейт (``db.write``), квотирование идентификаторов,
    tenant-скоуп, лимит размера батча, валидный профиль по умолчанию.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False
    required_capability: ClassVar[str | None] = "db.write"

    def __init__(
        self,
        *,
        table: str,
        items: list[dict[str, Any]] | None = None,
        key_field: str = "id",
        profile: str = AUTO_PROFILE,
        max_batch: int = MAX_BATCH_ROWS,
        tenant_column: str | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализирует batch-UPDATE.

        Args:
            table: Имя таблицы.
            items: Список dict для обновления (``None`` — берётся из body).
            key_field: Поле для WHERE-clause.
            profile: Профиль внешней БД (``"default"`` — авто-выбор).
            max_batch: Максимум строк в батче (``<= 0`` — без ограничения).
            tenant_column: Столбец tenant'а (включает tenant-скоуп).
            name: Имя процессора.

        """
        super().__init__(name=name or f"batch_update:{table}")
        self._table = table
        self._items = items
        self._key_field = key_field
        self._profile = profile
        self._max_batch = max_batch
        self._tenant_column = tenant_column

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет batch UPDATE через SQLAlchemy executemany с группировкой.

        Элементы группируются по идентичному набору update-колонок, каждая
        группа выполняется одним bulk-запросом. Все идентификаторы (table,
        columns, key_field) проходят SQL-injection валидацию (fail-fast).

        Args:
            exchange: Текущий exchange; items берутся из ``self._items`` либо
                из ``in_message.body``. Результат — в свойстве
                ``batch_update_result``.
            context: Контекст выполнения маршрута.

        Note:
            Количество затронутых строк — в ``batch_update_result.affected``.
            Исходные items передаются в ``out_message`` без изменений.

        """
        # ADR-0418: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action="write"):
            return

        items = self._items if self._items is not None else exchange.in_message.body
        if not isinstance(items, list) or not items:
            exchange.set_property("batch_update_result", {"affected": 0})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
        _check_batch_size(len(items), self._max_batch)
        _validate_identifier(self._key_field)
        # fail-fast: validate all column identifiers before touching DB
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"batch_update: каждый item должен быть dict, получено {type(item).__name__}"
                )
            for col in item:
                if col != self._key_field:
                    _validate_identifier(col)

        tenant_column, tenant_id = _tenant_scope(
            self._table, self._tenant_column, is_main=self._profile == AUTO_PROFILE
        )
        if tenant_column is not None:
            for item in items:
                _check_tenant_value(
                    self._table, tenant_column, tenant_id, item.get(tenant_column)
                )

        # Group items by identical update columns so each group can be
        # executed as a single bulk statement (executemany).
        from collections import defaultdict

        groups: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
        skipped = 0
        for item in items:
            key_value = item.get(self._key_field)
            if key_value is None:
                # ADR-0382: item без key-поля нельзя обновить — раньше он
                # молча терялся; теперь это видно в логе.
                skipped += 1
                continue
            updates = {
                k: v
                for k, v in item.items()
                if k != self._key_field and k != tenant_column
            }
            if not updates:
                skipped += 1
                continue
            params = dict(updates)
            params["_key"] = key_value
            if tenant_column is not None and tenant_id is not None:
                params["_tenant_id"] = tenant_id
            groups[frozenset(updates.keys())].append(params)
        if skipped:
            _logger.warning(
                "batch_update: пропущено %d item'ов без key-поля '%s' (table=%s)",
                skipped,
                self._key_field,
                self._table,
            )

        bundle = _resolve_bundle(self._profile)
        dialect = _dialect_of(bundle)
        table_sql = _quote(self._table, dialect)
        key_sql = _quote(self._key_field, dialect)
        total_affected = 0
        async with bundle.async_session_maker() as session:
            for cols, params_list in groups.items():
                set_clause = ", ".join(
                    f"{_quote(col, dialect)} = :{col}" for col in cols
                )
                stmt_text = (
                    f"UPDATE {table_sql} SET {set_clause} WHERE {key_sql} = :_key"
                )
                if tenant_column is not None:
                    stmt_text += f" AND {_quote(tenant_column, dialect)} = :_tenant_id"
                result = await session.execute(text(stmt_text), params_list)
                total_affected += getattr(result, "rowcount", 0)
            await session.commit()
        exchange.set_property("batch_update_result", {"affected": total_affected})
        exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        spec: dict[str, Any] = {
            "table": self._table,
            "items": self._items,
            "key_field": self._key_field,
            "profile": self._profile,
        }
        if self._max_batch != MAX_BATCH_ROWS:
            spec["max_batch"] = self._max_batch
        if self._tenant_column is not None:
            spec["tenant_column"] = self._tenant_column
        return {"batch_update": spec}


class BatchDeleteProcessor(BaseProcessor):
    """Batch DELETE через SQLAlchemy core (IN-clause).

    ADR-0418: capability-гейт (``db.write``), квотирование идентификаторов,
    tenant-скоуп, лимит размера батча, валидный профиль по умолчанию.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False
    required_capability: ClassVar[str | None] = "db.write"

    def __init__(
        self,
        *,
        table: str,
        ids: list[Any] | None = None,
        key_field: str = "id",
        profile: str = AUTO_PROFILE,
        max_batch: int = MAX_BATCH_ROWS,
        tenant_column: str | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализирует batch-DELETE.

        Args:
            table: Имя таблицы.
            ids: Список ID для удаления (``None`` — берётся из body).
            key_field: Поле для WHERE-clause.
            profile: Профиль внешней БД (``"default"`` — авто-выбор).
            max_batch: Максимум ID в батче (``<= 0`` — без ограничения).
            tenant_column: Столбец tenant'а (включает tenant-скоуп).
            name: Имя процессора.

        """
        super().__init__(name=name or f"batch_delete:{table}")
        self._table = table
        self._ids = ids
        self._key_field = key_field
        self._profile = profile
        self._max_batch = max_batch
        self._tenant_column = tenant_column

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет batch DELETE через SQLAlchemy (``IN (:ids)`` — все диалекты).

        IDs берутся из ``self._ids`` либо ``in_message.body``. Table и key_field
        проходят SQL-injection валидацию.

        Args:
            exchange: Текущий exchange; ids — из ``self._ids`` или body.
                Результат — в свойстве ``batch_delete_result``.
            context: Контекст выполнения маршрута.

        """
        # ADR-0418: capability-гейт до любого обращения к БД.
        if not await self.auth_check(exchange, action="write"):
            return

        ids = self._ids if self._ids is not None else exchange.in_message.body
        if not isinstance(ids, list) or not ids:
            exchange.set_property("batch_delete_result", {"affected": 0})
            exchange.set_out(body=ids, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
        _check_batch_size(len(ids), self._max_batch)
        _validate_identifier(self._key_field)
        tenant_column, tenant_id = _tenant_scope(
            self._table, self._tenant_column, is_main=self._profile == AUTO_PROFILE
        )

        bundle = _resolve_bundle(self._profile)
        dialect = _dialect_of(bundle)
        table_sql = _quote(self._table, dialect)
        key_sql = _quote(self._key_field, dialect)
        # ADR-0382: ``= ANY(:ids)`` — только PostgreSQL (на sqlite/mysql/
        # oracle «no such function: ANY»). Expanding bindparam даёт
        # переносимый ``IN (:id_1, :id_2, ...)`` для всех диалектов.
        stmt_text = f"DELETE FROM {table_sql} WHERE {key_sql} IN :ids"
        params: dict[str, Any] = {"ids": list(ids)}
        if tenant_column is not None and tenant_id is not None:
            stmt_text += f" AND {_quote(tenant_column, dialect)} = :_tenant_id"
            params["_tenant_id"] = tenant_id
        stmt = text(stmt_text).bindparams(bindparam("ids", expanding=True))
        async with bundle.async_session_maker() as session:
            result = await session.execute(stmt, params)
            await session.commit()
            affected = getattr(result, "rowcount", len(ids))
            exchange.set_property("batch_delete_result", {"affected": affected})
            exchange.set_out(body=ids, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        spec: dict[str, Any] = {
            "table": self._table,
            "ids": self._ids,
            "key_field": self._key_field,
            "profile": self._profile,
        }
        if self._max_batch != MAX_BATCH_ROWS:
            spec["max_batch"] = self._max_batch
        if self._tenant_column is not None:
            spec["tenant_column"] = self._tenant_column
        return {"batch_delete": spec}
