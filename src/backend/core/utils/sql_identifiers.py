"""S-30 (Wave 13, Q18): allowlist-валидация SQL-идентификаторов.

Bind-параметры применимы только к *значениям*. Имена таблиц, колонок,
индексов и JSON-путей, которые попадают в SQL через f-string, нужно
проверять allowlist-регексом (ADR-0112, TD-021): кавычки, пробелы и
спецсимволы в имени немедленно превращают его в исполняемый SQL.

Модуль живёт в слое ``core``, его импортируют подсистемы
``infrastructure`` (обратный импорт core → infrastructure запрещён,
ADR-0284 §1.1).

Разрешённые формы:

* ``validate_identifier`` — одиночный идентификатор
  ``[A-Za-z_][A-Za-z0-9_]*`` (имя таблицы, имя индекса);
* ``validate_path_key`` — JSON-путь из таких же сегментов, разделённых
  точками (``parent.child`` → ``$.parent.child``);
* ``validate_qualified_identifier`` — квалифицированное имя объекта
  (``name`` / ``schema.name`` / ``db.schema.name``): до 3 сегментов,
  каждый — по правилу ``validate_identifier`` (ADR-0365).
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ("validate_identifier", "validate_path_key", "validate_qualified_identifier")

# `\Z` вместо `$`: `$` в regex совпадает и перед завершающим `\n`,
# `\Z` — строго в конце строки (иначе `"orders\n"` проходил бы валидацию).
_IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
_PATH_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\Z")

#: Максимальное число сегментов в квалифицированном имени объекта.
_MAX_QUALIFIED_SEGMENTS: Final = 3


def validate_identifier(value: str, *, context: str) -> str:
    """Проверить, что identifier безопасен для интерполяции в SQL.

    Разрешён только одиночный SQL-идентификатор: ``[A-Za-z_][A-Za-z0-9_]*``.
    Кавычки, пробелы, спецсимволы и trailing newline — запрещены.

    Args:
        value: Проверяемое имя таблицы/индекса/колонки.
        context: Контекст для сообщения об ошибке (например ``"audit.table"``).

    Returns:
        То же значение ``value`` (для удобства inline-использования).

    Raises:
        ValueError: Если значение не является валидным идентификатором.

    """
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise ValueError(
            f"Недопустимый SQL identifier в контексте '{context}': {value!r}. "
            "Ожидается [A-Za-z_][A-Za-z0-9_]* (без кавычек и спецсимволов)."
        )
    return value


def validate_qualified_identifier(value: str, *, context: str) -> str:
    """Проверить квалифицированное имя SQL-объекта (ADR-0365).

    Допустимы ``name``, ``schema.name``, ``db.schema.name`` — до 3
    сегментов, каждый из которых проверяется каноном
    :func:`validate_identifier`. Кавычки, пробелы, спецсимволы и
    trailing newline — запрещены.

    Args:
        value: Проверяемое квалифицированное имя (view/function/procedure).
        context: Контекст для сообщения об ошибке (например ``"view"``).

    Returns:
        То же значение ``value`` (для удобства inline-использования).

    Raises:
        ValueError: Если значение не является валидным квалифицированным
            именем.

    """
    if not isinstance(value, str):
        raise ValueError(
            f"Недопустимый SQL identifier в контексте '{context}': {value!r}. "
            "Ожидается name / schema.name / db.schema.name "
            "без кавычек и спецсимволов."
        )
    segments = value.split(".")
    if not 1 <= len(segments) <= _MAX_QUALIFIED_SEGMENTS:
        raise ValueError(
            f"Недопустимый SQL identifier в контексте '{context}': {value!r}. "
            "Ожидается name / schema.name / db.schema.name "
            "без кавычек и спецсимволов."
        )
    for segment in segments:
        try:
            validate_identifier(segment, context=context)
        except ValueError as exc:
            raise ValueError(
                f"Недопустимый SQL identifier в контексте '{context}': {value!r}. "
                "Ожидается name / schema.name / db.schema.name "
                "без кавычек и спецсимволов."
            ) from exc
    return value


def validate_path_key(value: str, *, context: str) -> str:
    """Проверить, что ключ — безопасный JSON-путь (``$.parent.child``).

    Каждый сегмент пути должен совпадать с ``[A-Za-z_][A-Za-z0-9_]*``;
    сегменты разделяются точкой. Точка разрешена, т.к. путь подставляется
    в ``json_extract(body, '$.<key>')`` — вложенные JSON-документы должны
    фильтроваться по ``parent.child``.

    Args:
        value: Проверяемый ключ фильтра (JSON-путь).
        context: Контекст для сообщения об ошибке.

    Returns:
        То же значение ``value`` (для удобства inline-использования).

    Raises:
        ValueError: Если значение не является валидным JSON-путём.

    """
    if not isinstance(value, str) or not _PATH_RE.match(value):
        raise ValueError(
            f"Недопустимый ключ фильтра в контексте '{context}': {value!r}. "
            "Ожидается JSON-путь вида name / parent.child "
            "(каждый сегмент — [A-Za-z_][A-Za-z0-9_]*)."
        )
    return value
