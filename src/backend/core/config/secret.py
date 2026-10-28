"""Извлечение «сырого» значения секрета (ADR-0375, wave 14 — ЧАСТЬ D).

Поля настроек, которые реально являются секретами, типизированы как
``SecretStr`` (ADR-0373/ADR-0375): значение маскируется в ``repr`` и в
логах. Читателям, которым нужна обычная строка (HTTP-заголовок, DSN,
аргумент SDK), нужен явный ``get_secret_value()``.

Хелпер :func:`secret_value` — единственная точка такого извлечения:
он терпим к ``None`` и к обычным ``str`` (часть полей ещё не типизирована
и остаётся ``str`` — см. owner-задачи в ADR-0375), поэтому вызывающий код
не различает типизированное и нетипизированное поле.
"""

from __future__ import annotations

from pydantic import SecretStr

__all__ = ("secret_value",)


def secret_value(value: SecretStr | str | None) -> str:
    """Возвращает строковое значение секрета.

    Поддерживает и ``SecretStr``, и «утиные» SecretStr-подобные объекты
    (например, ``MagicMock`` в тестах) — поэтому вызывающий код не должен
    различать типизированное и нетипизированное поле.

    Args:
        value: ``SecretStr``, обычная строка или ``None``.

    Returns:
        Значение секрета; пустая строка для ``None``.
    """
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value)
