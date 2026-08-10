"""Регрессионные тесты для extensions/test_plug — entry-class + on_register_actions (Sprint 8 Extensions 1).

Контракт:

* ``extensions/test_plug/plugin.toml`` объявляет
  ``entry_class = "extensions.test_plug.plugin.TestPlugPlugin"``
  (см. ``extensions/test_plug/plugin.toml:5``).
* ``extensions/test_plug/plugin.py`` обязан импортироваться под этим
  dotted-path и предоставлять ``TestPlugPlugin``-наследника
  ``BasePlugin`` (``src.backend.core.interfaces.plugin.BasePlugin``).

Эти тесты ловят регрессии, при которых файл плагина теряет канонический
импорт ``BasePlugin`` (Sprint 36 BugBash: ``gd_integration_tools.*`` namespace
не существует — единственный рабочий путь ``src.backend.core.interfaces.plugin``)
или entry-class из манифеста расходится с реальным модулем.

Покрытие:

1. ``test_entry_class_imports_successfully`` — dotted-path из манифеста резолвится.
2. ``test_entry_class_matches_plugin_toml_manifest`` — entry_class в plugin.toml ==
   реальный импортируемый класс.
3. ``test_test_plug_inherits_base_plugin`` — TestPlugPlugin — subclass of canonical
   ``BasePlugin`` (контракт ``extensions/__init__.py``).
4. ``test_test_plug_on_register_actions_default_noop`` — унаследованный hook
   ``on_register_actions`` (default no-op из BasePlugin) не ломается на минимальном
   плагине и не дёргает ``ActionRegistryProtocol.register``.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from collections.abc import Callable


_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_TEST_PLUG_DIR = _PROJECT_ROOT / "extensions" / "test_plug"
_PLUGIN_MODULE = "extensions.test_plug.plugin"
_PLUGIN_CLASS = "TestPlugPlugin"


class _StubRegistry:
    """Заглушка ActionRegistryProtocol для проверки default no-op.

    Реализует минимальный контракт ``register`` (sync, см.
    ``src/backend/core/interfaces/plugin.py:39`` — ActionRegistryProtocol
    объявлен как ``@runtime_checkable Protocol`` с одним методом).
    """

    def __init__(self) -> None:
        """Инициализирует пустой буфер вызовов ``register``."""

        self.registered: list[str] = []

    def register(
        self, action_id: str, handler: Callable[..., Any], *, spec: Any | None = None,
    ) -> None:
        """Сохраняет переданный action_id для последующего assert."""

        self.registered.append(action_id)


def test_entry_class_imports_successfully() -> None:
    """``extensions.test_plug.plugin.TestPlugPlugin`` импортируется через dotted-path.

    Бросает ``ImportError`` если цикл 2 (BugBash) снова ввёл невалидный
    ``from gd_integration_tools.... import BasePlugin`` (такого namespace нет).
    """

    module = importlib.import_module(_PLUGIN_MODULE)
    plugin_cls = getattr(module, _PLUGIN_CLASS, None)
    assert plugin_cls is not None, (
        f"{_PLUGIN_MODULE}.{_PLUGIN_CLASS} должен быть определён"
    )


def test_entry_class_matches_plugin_toml_manifest() -> None:
    """``entry_class`` из plugin.toml резолвится в реальный импортируемый класс.

    Spec: ``extensions/test_plug/plugin.toml:5``.
    """

    raw = tomllib.loads((_TEST_PLUG_DIR / "plugin.toml").read_text(encoding="utf-8"))
    entry_class = raw["entry_class"]

    module_path, _, class_name = entry_class.rpartition(".")
    assert module_path == _PLUGIN_MODULE, (
        f"entry_class должен указывать на {_PLUGIN_MODULE}, got: {module_path}"
    )

    module = importlib.import_module(module_path)
    plugin_cls = getattr(module, class_name, None)
    assert plugin_cls is not None, f"Класс {class_name} не найден в {module_path}"


def test_test_plug_inherits_base_plugin() -> None:
    """``TestPlugPlugin`` — subclass of canonical ``BasePlugin``.

    Канонический ``BasePlugin`` живёт в ``src.backend.core.interfaces.plugin``
    (см. ``extensions/__init__.py:37`` — canonical prelude для extension'ов).
    """

    plugin_cls = importlib.import_module(_PLUGIN_MODULE).__dict__[_PLUGIN_CLASS]
    assert issubclass(plugin_cls, BasePlugin), (
        f"{_PLUGIN_CLASS} должен наследовать BasePlugin из "
        "src.backend.core.interfaces.plugin"
    )


@pytest.mark.asyncio
async def test_test_plug_on_register_actions_default_noop() -> None:
    """Унаследованный ``on_register_actions`` работает как default no-op из BasePlugin.

    Контракт ``BasePlugin.on_register_actions`` (см.
    ``src/backend/core/interfaces/plugin.py:202``): default no-op async-метод.
    ``TestPlugPlugin`` не переопределяет его → вызов не должен дёргать
    ``ActionRegistryProtocol.register``.
    """

    plugin_cls = importlib.import_module(_PLUGIN_MODULE).__dict__[_PLUGIN_CLASS]
    plugin = plugin_cls()
    registry = _StubRegistry()

    # BasePlugin.on_register_actions — default no-op: завершается без ошибки.
    await plugin.on_register_actions(registry)

    assert registry.registered == [], (
        "Default no-op из BasePlugin.on_register_actions не должен вызывать "
        "registry.register"
    )
