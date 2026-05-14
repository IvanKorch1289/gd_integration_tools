# ruff: noqa: S101
"""Smoke-тесты экземпляра UsersPlugin (lifecycle)."""

from __future__ import annotations

import pytest

from extensions.core_entities.users.plugin import UsersPlugin
from src.backend.core.interfaces.plugin import BasePlugin


def test_users_plugin_is_baseplugin_subclass() -> None:
    """UsersPlugin наследуется от BasePlugin."""
    assert issubclass(UsersPlugin, BasePlugin)
    assert UsersPlugin.name == "core_entities_users"
    assert UsersPlugin.version == "1.0.0"


@pytest.mark.asyncio
async def test_users_plugin_lifecycle_smoke() -> None:
    """on_load + on_shutdown отрабатывают без исключений."""
    plugin = UsersPlugin()
    # PluginContext мокаем как минимальный объект — UsersPlugin сохраняет
    # его атрибутом, дальнейшего использования нет.
    await plugin.on_load(ctx=object())  # type: ignore[arg-type]
    assert plugin._ctx is not None
    await plugin.on_shutdown()
