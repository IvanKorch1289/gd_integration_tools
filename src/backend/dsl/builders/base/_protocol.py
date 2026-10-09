"""Backward-compat shim.

Каноническое расположение — :mod:`src.backend.dsl.builders._protocol`.

Модуль вынесен на уровень пакета ``builders``, потому что его импорт из
поддерева ``transport`` выполнял ``builders.base.__init__``, а тот тянет
``integration``, который импортирует ``transport`` — циклический импорт,
из-за которого ``from src.backend.dsl.builders.transport.persistence import
PersistenceMixin`` падал с ImportError.
"""

from __future__ import annotations

from src.backend.dsl.builders._protocol import (  # noqa: F401
    _RouteBuilderProtocol as _RouteBuilderProtocol,
)

__all__ = ("_RouteBuilderProtocol",)
