# ruff: noqa: S101
"""Smoke-тест для :class:`FilesPlugin` (lifecycle-хуки).

Проверяет:
* ``FilesPlugin`` импортируется и наследует :class:`BasePlugin`;
* ``on_load`` / ``on_shutdown`` корректно срабатывают без ошибок.
"""

from __future__ import annotations

import pytest

from extensions.core_entities.files.plugin import FilesPlugin
from src.backend.core.interfaces.plugin import BasePlugin


def test_files_plugin_is_base_plugin_subclass() -> None:
    """``FilesPlugin`` — корректный :class:`BasePlugin`-наследник."""
    plugin = FilesPlugin()
    assert isinstance(plugin, BasePlugin)
    assert plugin.name == "core_entities_files"
    assert plugin.version == "1.0.0"


@pytest.mark.asyncio
async def test_files_plugin_lifecycle_runs() -> None:
    """Lifecycle ``on_load`` → ``on_shutdown`` не падает (без БД)."""
    plugin = FilesPlugin()

    class _StubCtx:
        plugin_name = "core_entities_files"
        actions = None
        repositories = None
        processors = None
        config: dict = {}

    await plugin.on_load(_StubCtx())  # type: ignore[arg-type]
    await plugin.on_shutdown()
