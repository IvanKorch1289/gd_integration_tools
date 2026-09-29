"""Регрессия: ``StructlogLogger.name`` возвращает настоящее имя логгера.

Дефект: свойство проверяло ``hasattr(inner, "_logger")`` первым. У
``structlog.BoundLoggerLazyProxy`` этот атрибут ЕСТЬ, но до биндинга равен
``None``, поэтому ``getattr(inner._logger, "name", default)`` уходил в
``default`` и возвращал ``inner.__class__.__name__`` — то есть строку
'BoundLoggerLazyProxy' вместо имени логгера. Корректное ``inner.name``
лежало во второй ветке, которая никогда не выполнялась.

Свойство документировано как «обратная совместимость: logger.name →
structlog logger name», поэтому возврат имени класса прокси — регресс
наблюдаемости: по логам и метрикам нельзя было понять, чей это логгер.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.logging.structlog_backend import StructlogLogger


class _InnerWithName:
    """Объект с собственным ``.name`` — самый прямой источник имени."""

    name = "direct.name"


class _InnerBound:
    """Стандартная обёртка: имя спрятано в ``_logger.name``."""

    def __init__(self, name: str) -> None:
        self._logger = type("Std", (), {"name": name})()


class _InnerLazyUnbound:
    """``BoundLoggerLazyProxy`` до биндинга: ``_logger`` есть, но равен None."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._logger = None


class _InnerBare:
    """Ни ``.name``, ни ``_logger.name`` — откат на имя класса."""

    pass


def test_prefers_inner_own_name() -> None:
    """Собственный ``.name`` объекта — приоритетная ветка."""
    assert StructlogLogger(_InnerWithName()).name == "direct.name"


def test_lazy_proxy_returns_real_name_not_proxy_class() -> None:
    """Ядро дефекта: небандленный lazy-proxy давал 'BoundLoggerLazyProxy'."""
    logger = StructlogLogger(_InnerLazyUnbound("infrastructure.cache.factory"))
    assert logger.name == "infrastructure.cache.factory"
    assert logger.name != "BoundLoggerLazyProxy"


def test_falls_back_to_nested_stdlib_logger() -> None:
    """Хвостовая ветка сохранена: имя из ``_logger.name``."""
    assert StructlogLogger(_InnerBound("database")).name == "database"


def test_falls_back_to_class_name_when_nothing_available() -> None:
    """Последний откат — имя класса, чтобы свойство никогда не падало."""
    inner = _InnerBare()
    assert StructlogLogger(inner).name == inner.__class__.__name__


def test_name_never_raises_on_none_inner() -> None:
    """Даже полностью пустой inner не должен ронять логирование."""
    assert StructlogLogger(object()).name == "object"


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        (_InnerWithName(), "direct.name"),
        (_InnerLazyUnbound("a.b.c"), "a.b.c"),
        (_InnerBound("database"), "database"),
    ],
)
def test_existing_call_sites_keep_their_names(inner: object, expected: str) -> None:
    """Все три источника имени дают ожидаемое значение."""
    assert StructlogLogger(inner).name == expected
