# ruff: noqa: SLF001
"""Conftest для tests/unit/plugins/composition — cleanup importlib stub pollution.

**Проблема (S124 W3)**: ``lifecycle/test_outbox_dispatcher_cutover.py``
использует ``importlib.util`` hack, чтобы обойти pre-existing баг в
``src/backend/plugins/composition/__init__.py`` (graphQL router).

Конкретно — он stub'ит sys.modules:
- ``src.backend.plugins.composition`` → ``types.ModuleType(...)`` (empty stub)
- ``src.backend.plugins.composition.lifecycle`` → empty stub
- ``src.backend.plugins.composition.lifecycle.{bootstrap,protocols,v11,watchers}``
  → empty stubs
- + ``lifespan`` / ``startup`` грузятся через importlib.util и тоже
  кладутся в sys.modules (с ``__name__='_lifespan_isolated'``)

После collection ``test_outbox_dispatcher_cutover.py`` все top-level
composition-тесты ломаются с
``ImportError: cannot import name 'app_factory' from
'src.backend.plugins.composition' (unknown location)``.

**Решение**: ``pytest_collectstart`` hook для File-коллекторов:
перед collection каждого .py файла удаляем polluted stub-модули.
Следующий ``import`` подтянет настоящий пакет через ``__init__.py``.
"""

from __future__ import annotations

import sys

import pytest

# Все модули, которые test_outbox_dispatcher_cutover.py может залипнуть
_POLLUTED_KEYS = (
    "src.backend.plugins.composition",
    "src.backend.plugins.composition.lifecycle",
    "src.backend.plugins.composition.lifecycle.bootstrap",
    "src.backend.plugins.composition.lifecycle.protocols",
    "src.backend.plugins.composition.lifecycle.v11",
    "src.backend.plugins.composition.lifecycle.watchers",
    "src.backend.plugins.composition.lifecycle.startup",
    "src.backend.plugins.composition.lifecycle.lifespan",
    "src.backend.plugins.composition.lifecycle.shutdown",
    "src.backend.plugins.composition.lifecycle.signals",
)


def _is_polluted(key: str) -> bool:
    """Модуль polluted, если он — empty stub (нет ``__file__`` при наличии
    ``__path__``) или fake с ``__name__`` начинающимся на ``_`` и содержащим
    ``isolated``.
    """
    mod = sys.modules.get(key)
    if mod is None:
        return False
    # Fake с importlib.util — имя идёт через _lifespan_isolated, _isolated_*
    fake_name = getattr(mod, "__name__", "") or ""
    if "isolated" in fake_name or fake_name.startswith("_isolated_"):
        return True
    # Empty stub-package: types.ModuleType(name) с __path__, но без __file__
    file = getattr(mod, "__file__", None)
    if file is None and hasattr(mod, "__path__"):
        return True
    return False


def _cleanup() -> int:
    """Удаляет все polluted модули. Возвращает кол-во удалённых."""
    removed = 0
    for k in _POLLUTED_KEYS:
        if k in sys.modules and _is_polluted(k):
            del sys.modules[k]
            removed += 1
    return removed


@pytest.hookimpl(tryfirst=True)
def pytest_collectstart(collector: pytest.Collector) -> None:
    """Перед collection каждого File — cleanup pollution от предыдущих."""
    if isinstance(collector, pytest.File):
        _cleanup()
