# ruff: noqa: S101
"""Smoke-тесты экземпляра OrdersPlugin (lifecycle)."""

from __future__ import annotations

import pytest

from extensions.core_entities.orders.plugin import OrdersPlugin
from src.backend.core.interfaces.plugin import BasePlugin


def test_orders_plugin_is_baseplugin_subclass() -> None:
    """OrdersPlugin наследуется от BasePlugin."""
    assert issubclass(OrdersPlugin, BasePlugin)
    assert OrdersPlugin.name == "core_entities_orders"
    assert OrdersPlugin.version == "1.0.0"


@pytest.mark.asyncio
async def test_orders_plugin_lifecycle_smoke() -> None:
    """on_load + on_shutdown отрабатывают без исключений."""
    plugin = OrdersPlugin()
    await plugin.on_load(ctx=object())  # type: ignore[arg-type]
    assert plugin._ctx is not None
    await plugin.on_shutdown()
