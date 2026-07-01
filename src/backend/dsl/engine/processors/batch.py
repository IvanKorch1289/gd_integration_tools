"""Batch DB processors — INSERT / UPDATE / DELETE через SQLAlchemy core."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import text

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

#: Разрешённые символы в имени таблицы (schema.table или table).
_TABLE_NAME_RE: re.Pattern[str] = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$"
)

#: Разрешённые символы в SQL-идентификаторе (колонка, alias и т.д.).
_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Invalid identifier: {name!r}")


# lazy-evaluated at module level for testability
_get_external_db_registry = None


def _lazy_get_external_db_registry():
    global _get_external_db_registry
    if _get_external_db_registry is None:
        from src.backend.infrastructure.database.database import (
            get_external_db_registry,
        )

        _get_external_db_registry = get_external_db_registry
    return _get_external_db_registry


if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("BatchDeleteProcessor", "BatchInsertProcessor", "BatchUpdateProcessor")


def _validate_table(table: str) -> None:
    """Проверяет, что имя таблицы не содержит SQL-injection."""
    if not _TABLE_NAME_RE.fullmatch(table):
        raise ValueError(f"Invalid table name: {table!r}")


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
        # fail-fast: validate all column identifiers before touching DB
        first = items[0]
        for col in first:
            _validate_identifier(col)
        bundle = _lazy_get_external_db_registry()().get_bundle(self._profile)
        # executemany через list[dict]
        columns = ", ".join(first.keys())
        placeholders = ", ".join(f":{k}" for k in first)
        stmt_text = f"INSERT INTO {self._table} ({columns}) VALUES ({placeholders})"  # noqa: S608
        async with bundle.async_session_maker() as session:
            result = await session.execute(text(stmt_text), items)
            await session.commit()
            affected = getattr(result, "rowcount", len(items))
            exchange.set_property("batch_insert_result", {"affected": affected})
            exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
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
            for col in item:
                if col != self._key_field:
                    _validate_identifier(col)

        # Group items by identical update columns so each group can be
        # executed as a single bulk statement (executemany).
        from collections import defaultdict

        groups: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            key_value = item.get(self._key_field)
            if key_value is None:
                continue
            updates = {k: v for k, v in item.items() if k != self._key_field}
            if not updates:
                continue
            params = dict(updates)
            params["_key"] = key_value
            groups[frozenset(updates.keys())].append(params)

        bundle = _lazy_get_external_db_registry()().get_bundle(self._profile)
        total_affected = 0
        async with bundle.async_session_maker() as session:
            for cols, params_list in groups.items():
                set_clause = ", ".join(f"{k} = :{k}" for k in cols)
                stmt_text = (
                    f"UPDATE {self._table} SET {set_clause} "  # noqa: S608
                    f"WHERE {self._key_field} = :_key"
                )
                result = await session.execute(text(stmt_text), params_list)
                total_affected += getattr(result, "rowcount", 0)
            await session.commit()
        exchange.set_property("batch_update_result", {"affected": total_affected})
        exchange.set_out(body=items, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
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
        """Выполняет batch DELETE через SQLAlchemy (``= ANY(:ids)`` для Postgres).

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
            # Postgres-compatible: = ANY(:ids); fallback IN для остальных
            stmt_text = f"DELETE FROM {self._table} WHERE {self._key_field} = ANY(:ids)"  # noqa: S608
            result = await session.execute(text(stmt_text), {"ids": list(ids)})
            await session.commit()
            affected = getattr(result, "rowcount", len(ids))
            exchange.set_property("batch_delete_result", {"affected": affected})
            exchange.set_out(body=ids, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "batch_delete": {
                "table": self._table,
                "ids": self._ids,
                "key_field": self._key_field,
                "profile": self._profile,
            }
        }
