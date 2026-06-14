"""S111 W2 — тесты для декомпозиции lifespan.py на startup/shutdown/signals.

Покрывают (5 NEW tests):
1. ``lifespan._register_outbox_dispatcher`` ре-экспортируется из ``startup``
   (backward compat — S64 W3 test ссылается).
2. ``startup.run_startup`` существует с правильной сигнатурой.
3. ``startup._register_outbox_dispatcher`` существует.
4. ``shutdown.run_shutdown`` существует с правильной сигнатурой.
5. ``signals.install_signal_handlers`` no-op в pytest-окружении.

Используется isolated-loading pattern (как в test_outbox_dispatcher_cutover.py)
для обхода pre-existing import-bugs в ``plugins/composition/__init__.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Isolated module loader
# ─────────────────────────────────────────────────────────────────────────────


_LIFECYCLE_DIR = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "src"
    / "backend"
    / "plugins"
    / "composition"
    / "lifecycle"
)


def _stub_broken_packages() -> None:
    """Stub broken package __init__ + module-level deps.

    Plugins/composition package has pre-existing import-bugs (graphql_router),
    so we stub the package itself + any composition.lifecycle subpackage
    to avoid triggering their __init__.py.
    """
    broken_pkgs = {
        "src.backend.plugins.composition": True,
        "src.backend.plugins.composition.lifecycle": True,
    }
    for mod_name, is_package in broken_pkgs.items():
        if mod_name not in sys.modules:
            _stub = types.ModuleType(mod_name)
            if is_package:
                _stub.__path__ = []  # type: ignore[attr-defined]
            sys.modules[mod_name] = _stub

    # Module-level stubs for the deps that lifespan.py imports at module level.
    module_level_stubs = {
        "src.backend.core.utils.task_registry.get_task_registry": MagicMock(),
        "src.backend.infrastructure.logging.factory.get_logger": MagicMock(
            return_value=MagicMock()
        ),
    }
    for full_name, stub_obj in module_level_stubs.items():
        _existing = sys.modules.get(full_name)
        if _existing is None:
            _stub = types.ModuleType(full_name)
            setattr(_stub, full_name.rsplit(".", 1)[-1], stub_obj)
            sys.modules[full_name] = _stub
        else:
            setattr(_existing, full_name.rsplit(".", 1)[-1], stub_obj)


def _load_isolated(filename: str) -> ModuleType:
    """Load module from lifecycle/ as isolated module (real path, no __init__)."""
    path = _LIFECYCLE_DIR / filename
    mod_name = f"_isolated_{filename[:-3]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def signals_module() -> ModuleType:
    """Load signals.py isolated."""
    _stub_broken_packages()
    return _load_isolated("signals.py")


@pytest.fixture(scope="module")
def startup_module() -> ModuleType:
    """Load startup.py isolated."""
    _stub_broken_packages()
    return _load_isolated("startup.py")


@pytest.fixture(scope="module")
def shutdown_module() -> ModuleType:
    """Load shutdown.py isolated."""
    _stub_broken_packages()
    return _load_isolated("shutdown.py")


@pytest.fixture(scope="module")
def lifespan_module(startup_module: ModuleType) -> ModuleType:
    """Load lifespan.py isolated (after startup, since it re-exports from it)."""
    # Регистрируем startup в sys.modules чтобы lifespan.py нашёл его.
    sys.modules[
        "src.backend.plugins.composition.lifecycle.startup"
    ] = startup_module
    return _load_isolated("lifespan.py")


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_lifespan_reexports_startup_function(
    lifespan_module: ModuleType, startup_module: ModuleType
) -> None:
    """``lifespan._register_outbox_dispatcher`` ре-экспортируется из startup.

    Backward compat: S64 W3 test (``test_outbox_dispatcher_cutover.py``)
    импортирует функцию из ``lifespan``. После S111 W2 рефактора функция
    переехала в ``startup``, но lifespan.py должен её ре-экспортировать.
    """
    assert hasattr(lifespan_module, "_register_outbox_dispatcher")
    # ``from src.backend.plugins.composition.lifecycle.startup import X``
    # привязывает атрибут X в lifespan namespace к ТОМУ ЖЕ объекту, что и в startup.
    assert (
        lifespan_module._register_outbox_dispatcher
        is startup_module._register_outbox_dispatcher
    )


def test_startup_exposes_run_startup(startup_module: ModuleType) -> None:
    """``startup.py`` экспортирует ``run_startup(app, task_registry)``."""
    assert hasattr(startup_module, "run_startup")
    assert callable(startup_module.run_startup)
    # Проверяем signature через inspect.
    import inspect

    sig = inspect.signature(startup_module.run_startup)
    params = list(sig.parameters.keys())
    assert params == ["app", "task_registry"]


def test_startup_exposes_outbox_dispatcher(startup_module: ModuleType) -> None:
    """``startup.py`` экспортирует ``_register_outbox_dispatcher(app)`` (S64 W3)."""
    assert hasattr(startup_module, "_register_outbox_dispatcher")
    assert callable(startup_module._register_outbox_dispatcher)
    import inspect

    sig = inspect.signature(startup_module._register_outbox_dispatcher)
    params = list(sig.parameters.keys())
    assert params == ["app"]


def test_shutdown_exposes_run_shutdown(shutdown_module: ModuleType) -> None:
    """``shutdown.py`` экспортирует ``run_shutdown(app, task_registry)``."""
    assert hasattr(shutdown_module, "run_shutdown")
    assert callable(shutdown_module.run_shutdown)
    import inspect

    sig = inspect.signature(shutdown_module.run_shutdown)
    params = list(sig.parameters.keys())
    assert params == ["app", "task_registry"]


def test_signals_install_noop_in_pytest(signals_module: ModuleType) -> None:
    """``install_signal_handlers`` no-op когда ``PYTEST_CURRENT_TEST`` установлен.

    В тестах pytest имеет свой signal handling — наш handler конфликтовал бы
    (event loop close + signal install on closed loop = RuntimeError).
    """
    assert "PYTEST_CURRENT_TEST" in os.environ, (
        "Test should run under pytest (PYTEST_CURRENT_TEST must be set)"
    )

    shutdown_event = signals_module.install_signal_handlers()
    # No-op → пустой event (никогда не set).
    assert isinstance(shutdown_event, asyncio.Event)
    assert shutdown_event.is_set() is False
