"""Pytest-фикстура: pre-wired plugin loader для extensions/<name>/tests.

Загружает плагин из ``extensions/<name>/plugin.toml`` без полной
композиции lifespan-ветки приложения — достаточно для unit-тестов,
которые проверяют capability-gate, ActionSpec-регистрацию и
service-shadowing внутри plugin runtime.

Использование в ``extensions/<name>/tests/conftest.py``::

    from testkit.fixtures.plugin_loader import (
        plugin_runtime,
        loaded_plugin,
    )

    @pytest.fixture
    def my_plugin(loaded_plugin):
        return loaded_plugin("my_extension_name")

См. также :mod:`testkit.fixtures.db` (DB snapshot), :mod:`testkit.
fixtures.s3_mock` (S3 mock) — каноничная триада для extension-тестов.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

__all__ = ("plugin_runtime", "loaded_plugin")


@pytest.fixture(scope="session")
def plugin_runtime() -> Iterator[Any]:
    """Возвращает PluginRuntime (lazy import чтобы тесты без full deps работали).

    Зависимости подгружаются через ``uv sync --extra plugin-dev``.
    Без них fixture отдаёт ``pytest.skip``.
    """
    try:
        from src.backend.core.plugin_runtime.runtime import PluginRuntime
    except ImportError as exc:  # pragma: no cover — defensive
        pytest.skip(f"plugin_runtime недоступен: {exc}")

    runtime = PluginRuntime()
    yield runtime
    # graceful shutdown — runtime сам ничего не держит, capability-gate
    # сбрасывается при создании следующего экземпляра.


@pytest.fixture
def loaded_plugin(
    plugin_runtime: Any,
) -> Callable[[str], Any]:
    """Фабрика: загружает плагин по name (``extensions/<name>/plugin.toml``).

    Возвращает spec-объект с capabilities/provides — без bootstrap'а
    actions/routes/workflows (это делает full lifespan). Хорошо подходит
    для проверки manifest'а и base-capability-gate.

    Args:
        plugin_runtime: session-scoped PluginRuntime.

    Returns:
        Функцию ``loader(name) -> PluginSpec``.
    """

    def _load(name: str) -> Any:
        """Загружает plugin spec по имени.

        Args:
            name: Имя плагина (совпадает с именем директории в ``extensions/``).

        Returns:
            PluginSpec с capabilities/provides.

        Raises:
            pytest.Failed: Если загрузка не удалась.
        """
        try:
            spec = plugin_runtime.load(name)
        except Exception as exc:
            pytest.fail(f"plugin {name!r} load failed: {exc}")
        return spec

    return _load
