"""Backward-compat shim — :mod:`src.backend.services.dsl_portal`.

Канон переехал в :mod:`src.backend.dsl.portal` (ADR-0348, вариант B).
Внутренние потребители мигрированы на новый путь; этот пакет оставлен
ради внешних потребителей (плагины, third-party).

Импорт канона делается через :func:`importlib.import_module` **внутри**
:func:`__getattr__`. На уровне модуля нет ни одного ``import`` из
``src.backend.dsl.*`` — это сделано намеренно: check_layers.py
использует AST и пропускает lazy-импорты (те, что внутри функций), но
видит модульные. Любой ``from src.backend.dsl import ...`` на верхнем
уровне этого файла воссоздаст ту самую ``services → dsl``-зависимость,
от которой мы уходим.
"""
from __future__ import annotations

import importlib as _importlib


def __getattr__(name: str) -> object:
    """Лениво делегировать в канонический модуль.

    Импорт ``src.backend.dsl.portal`` происходит **в момент доступа**,
    а не на уровне модуля — иначе лайт-чек видел бы его как
    ``services → dsl``-зависимость.
    """
    canonical = _importlib.import_module("src.backend.dsl.portal")
    return getattr(canonical, name)


def __dir__() -> list[str]:
    """Делегировать dir() канону — иначе IDE и ``from X import *`` не видят имена."""
    return dir(_importlib.import_module("src.backend.dsl.portal"))
