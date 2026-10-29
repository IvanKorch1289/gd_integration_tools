"""Канон нейтрализации CSV formula-инъекции (OWASP CSV Injection).

ADR-0367 закрыл формулы в :class:`CsvWriteProcessor`, но
:class:`FileWriteProcessor` (ветка ``format="csv"``) писал значения «как
есть» — та же CSV-инъекция в другом процессоре (ADR-0390). Канон вынесен
в отдельный модуль, чтобы оба процессора использовали одну реализацию
(без межпакетного импорта ``components/`` → ``rpa/``).

Правило: строковое значение, начинающееся с ``=``/``+``/``-``/``@``,
получает префикс ``'`` — иначе при открытии файла в Excel/LibreOffice
ячейка исполняется как формула. Числа и прочие типы не изменяются.
"""

from __future__ import annotations

from typing import Any

__all__ = ("FORMULA_PREFIXES", "neutralize_formula")

#: Префиксы, которые Excel/LibreOffice трактуют как формулу.
FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@")


def neutralize_formula(value: Any) -> Any:
    """Нейтрализовать CSV formula-инъекцию (OWASP CSV Injection).

    Строковое значение, начинающееся с ``=``/``+``/``-``/``@``, получает
    префикс ``'`` — иначе при открытии файла в Excel/LibreOffice ячейка
    исполняется как формула. Числа и прочие типы не изменяются.

    Args:
        value: Значение ячейки (или имя колонки).

    Returns:
        Безопасное значение ячейки.

    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
