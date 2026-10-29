"""S-17 (Wave 13, Q11): allowlist-валидация SQL-идентификаторов для CDC.

Имена таблиц и timestamp-колонок из :class:`CDCSubscription` попадают
в SQL polling-/logminer-стратегий через f-string: bind-параметры в
SQLAlchemy применимы только к *значениям*, а не к идентификаторам.
Без allowlist-проверки имя вида ``"users; DROP TABLE x"`` становится
исполняемым SQL.

Канон правил — ``src.backend.core.utils.sql_identifiers`` (ADR-0112):
набор символов и форма сегмента определяются там. Здесь живёт только
CDC-специфика: допустимы ``name``, ``schema.name``, ``db.schema.name``
(до 3 сегментов) плюс ``escape_sql_literal`` для LogMiner.

Разрешённые формы: ``name``, ``schema.name``, ``db.schema.name``.
Кавычки, пробелы, спецсимволы и trailing newline — запрещены.
"""

from __future__ import annotations

from typing import Final

from src.backend.core.utils.sql_identifiers import (
    validate_identifier as _canonical_validate_identifier,
)
from src.backend.infrastructure.clients.external.cdc.events import CDCSubscription

__all__ = (
    "escape_sql_literal",
    "validate_identifier",
    "validate_subscription_identifiers",
)

#: CDC-специфика: до 3 сегментов (name / schema.name / db.schema.name).
_MAX_SEGMENTS: Final = 3


def _is_cdc_identifier(value: object) -> bool:
    """Проверить по канону: 1-3 сегмента, каждый — валидный identifier.

    Args:
        value: Проверяемое значение (может быть не строкой).

    Returns:
        ``True``, если значение — допустимый CDC-идентификатор.

    """
    if not isinstance(value, str):
        return False
    segments = value.split(".")
    if not 1 <= len(segments) <= _MAX_SEGMENTS:
        return False
    for segment in segments:
        try:
            _canonical_validate_identifier(segment, context="cdc.identifier")
        except ValueError:
            return False
    return True


def validate_identifier(value: str, *, context: str) -> str:
    """Проверить, что identifier безопасен для интерполяции в SQL.

    Разрешены только обычные SQL-идентификаторы: ``name``,
    ``schema.name``, ``db.schema.name``. Кавычки, пробелы, спецсимволы —
    запрещены. Правило сегмента делегировано канону
    ``core.utils.sql_identifiers.validate_identifier``.

    Используется как defence-in-depth поверх конфигурации подписки:
    даже если в ``CDCSubscription.tables`` / ``.timestamp_column``
    попадёт строка со спецсимволом, код упадёт с понятной ошибкой,
    а не выполнит неожиданный SQL.

    Args:
        value: Проверяемое имя таблицы/колонки.
        context: Контекст для сообщения об ошибке (например ``"cdc.tables"``).

    Returns:
        То же значение ``value`` (для удобства inline-использования).

    Raises:
        ValueError: Если значение не является валидным идентификатором.

    """
    if _is_cdc_identifier(value):
        return value
    raise ValueError(
        f"Недопустимый SQL identifier в контексте '{context}': {value!r}. "
        "Ожидается name / schema.name / db.schema.name "
        "без кавычек и спецсимволов."
    )


def validate_subscription_identifiers(sub: CDCSubscription) -> None:
    """Провалидировать имена таблиц и timestamp-колонку CDC-подписки.

    Вызывается на этапе подписки (fail-fast) и при старте стратегии —
    до того, как идентификаторы попадут в SQL.

    Args:
        sub: Подписка CDC (tables, timestamp_column).

    Raises:
        ValueError: Если хотя бы одно имя не является валидным
            SQL-идентификатором.

    """
    for table in sub.tables:
        validate_identifier(table, context=f"cdc.tables[{sub.id}]")
    validate_identifier(sub.timestamp_column, context=f"cdc.timestamp_column[{sub.id}]")
    if sub.primary_key:
        validate_identifier(sub.primary_key, context=f"cdc.primary_key[{sub.id}]")


def escape_sql_literal(value: str) -> str:
    """Экранировать одинарную кавычку для SQL-строкового литерала.

    Defence in depth для LogMiner: имена таблиц попадают в
    ``TABLE_NAME IN ('...')``. Валидация allowlist-ом уже исключает
    кавычки, но экранирование остаётся как второй слой защиты.

    Args:
        value: Значение строкового литерала.

    Returns:
        Значение с удвоенными одинарными кавычками.

    """
    return value.replace("'", "''")
