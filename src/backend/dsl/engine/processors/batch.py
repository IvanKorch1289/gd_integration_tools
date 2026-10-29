# ruff: noqa: S608 — false positive (controlled pattern)
# bandit: noqa: B608 — false positive (controlled pattern: table name
#   from __init__ (not user input), values bound via :param placeholders)
"""Batch DB processors — INSERT / UPDATE / DELETE через SQLAlchemy core."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import bindparam, text

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.core.utils.sql_identifiers import validate_identifier
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_logger = get_logger("dsl.batch")


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


__all__ = ("BatchDeleteProcessor", "BatchInsertProcessor", "BatchUpdateProcessor")


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


class BatchInsertProcessor(BaseProcessor):
    """Batch INSERT через SQLAlchemy core."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        table: str,
        items: list[dict[str, Any]] | None = None,
        profile: str = "default",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"batch_insert:{table}")
        self._table = table
        self._items = items
        self._profile = profile

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет пакетную вставку (INSERT) строк в таблицу через SQLAlchemy executemany.

        Args:
            exchange: Текущий обмен со списком записей для вставки.
            context: Контекст выполнения процессора.

        """
        items = self._items if self._items is not None else exchange.in_message.body
        if not isinstance(items, list) or not items:
            exchange.set_property("batch_insert_result", {"affected": 0})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
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

        bundle = _lazy_get_external_db_registry()().get_bundle(self._profile)
        # executemany через list[dict]: все items приводятся к общему набору
        # колонок, отсутствующие значения → NULL (данные не теряются).
        rows = [{col: item.get(col) for col in columns} for item in items]
        columns_sql = ", ".join(columns)
        placeholders = ", ".join(f":{col}" for col in columns)
        stmt_text = f"INSERT INTO {self._table} ({columns_sql}) VALUES ({placeholders})"
        async with bundle.async_session_maker() as session:
            result = await session.execute(text(stmt_text), rows)
            await session.commit()
            affected = getattr(result, "rowcount", len(items))
            exchange.set_property("batch_insert_result", {"affected": affected})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {
            "batch_insert": {
                "table": self._table,
                "items": self._items,
                "profile": self._profile,
            }
        }


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
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        table: str,
        items: list[dict[str, Any]] | None = None,
        key_field: str = "id",
        profile: str = "default",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"batch_update:{table}")
        self._table = table
        self._items = items
        self._key_field = key_field
        self._profile = profile

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
        items = self._items if self._items is not None else exchange.in_message.body
        if not isinstance(items, list) or not items:
            exchange.set_property("batch_update_result", {"affected": 0})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
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
            updates = {k: v for k, v in item.items() if k != self._key_field}
            if not updates:
                skipped += 1
                continue
            params = dict(updates)
            params["_key"] = key_value
            groups[frozenset(updates.keys())].append(params)
        if skipped:
            _logger.warning(
                "batch_update: пропущено %d item'ов без key-поля '%s' (table=%s)",
                skipped,
                self._key_field,
                self._table,
            )

        bundle = _lazy_get_external_db_registry()().get_bundle(self._profile)
        total_affected = 0
        async with bundle.async_session_maker() as session:
            for cols, params_list in groups.items():
                set_clause = ", ".join(f"{k} = :{k}" for k in cols)
                stmt_text = (
                    f"UPDATE {self._table} SET {set_clause} "
                    f"WHERE {self._key_field} = :_key"
                )
                result = await session.execute(text(stmt_text), params_list)
                total_affected += getattr(result, "rowcount", 0)
            await session.commit()
        exchange.set_property("batch_update_result", {"affected": total_affected})
        exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {
            "batch_update": {
                "table": self._table,
                "items": self._items,
                "key_field": self._key_field,
                "profile": self._profile,
            }
        }


class BatchDeleteProcessor(BaseProcessor):
    """Batch DELETE через SQLAlchemy core (IN-clause)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        table: str,
        ids: list[Any] | None = None,
        key_field: str = "id",
        profile: str = "default",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"batch_delete:{table}")
        self._table = table
        self._ids = ids
        self._key_field = key_field
        self._profile = profile

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
        ids = self._ids if self._ids is not None else exchange.in_message.body
        if not isinstance(ids, list) or not ids:
            exchange.set_property("batch_delete_result", {"affected": 0})
            exchange.set_out(body=ids, headers=dict(exchange.in_message.headers))
            return

        _validate_table(self._table)
        _validate_identifier(self._key_field)
        bundle = _lazy_get_external_db_registry()().get_bundle(self._profile)
        async with bundle.async_session_maker() as session:
            # ADR-0382: ``= ANY(:ids)`` — только PostgreSQL (на sqlite/mysql/
            # oracle «no such function: ANY»). Expanding bindparam даёт
            # переносимый ``IN (:id_1, :id_2, ...)`` для всех диалектов.
            stmt = text(
                f"DELETE FROM {self._table} WHERE {self._key_field} IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            result = await session.execute(stmt, {"ids": list(ids)})
            await session.commit()
            affected = getattr(result, "rowcount", len(ids))
            exchange.set_property("batch_delete_result", {"affected": affected})
            exchange.set_out(body=ids, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {
            "batch_delete": {
                "table": self._table,
                "ids": self._ids,
                "key_field": self._key_field,
                "profile": self._profile,
            }
        }
