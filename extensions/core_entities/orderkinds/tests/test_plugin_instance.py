# ruff: noqa: S101
"""Smoke-тест для :class:`OrderKindsPlugin` (lifecycle-хуки).

Проверяет:
* ``OrderKindsPlugin`` импортируется и наследует :class:`BasePlugin`;
* ``on_load`` / ``on_shutdown`` корректно срабатывают без ошибок.
"""

from __future__ import annotations

import pytest

from extensions.core_entities.orderkinds.plugin import OrderKindsPlugin
from src.backend.core.interfaces.plugin import BasePlugin


def test_orderkinds_plugin_is_base_plugin_subclass() -> None:
    """``OrderKindsPlugin`` — корректный :class:`BasePlugin`-наследник."""
    plugin = OrderKindsPlugin()
    assert isinstance(plugin, BasePlugin)
    assert plugin.name == "core_entities_orderkinds"
    assert plugin.version == "1.0.0"


@pytest.mark.asyncio
async def test_orderkinds_plugin_lifecycle_runs() -> None:
    """Lifecycle ``on_load`` → ``on_shutdown`` не падает (без БД)."""
    plugin = OrderKindsPlugin()

    class _StubCtx:
        plugin_name = "core_entities_orderkinds"
        actions = None
        repositories = None
        processors = None
        config: dict = {}

    await plugin.on_load(_StubCtx())  # type: ignore[arg-type]
    await plugin.on_shutdown()
