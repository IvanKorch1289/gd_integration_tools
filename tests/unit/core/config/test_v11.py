"""Tests for PluginLoaderSettings.

Canonical location is ``src.backend.core.config.plugin_loader``.
The legacy ``v11`` import path was removed (see settings.py: v11 = plugin_loader_settings).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.plugin_loader import PluginLoaderSettings


def _installed_version() -> str:
    """Версия установленного дистрибутива ядра."""
    from importlib.metadata import version

    return version("gd_advanced_tools")


class TestPluginLoaderSettings:
    def test_defaults(self) -> None:
        s = PluginLoaderSettings()
        assert s.plugin_loader_enabled is False
        # route_loader_enabled=True с 2026-10-06: подсистема V11-роутов была
        # выключена, из-за чего её reference-роуты молча устаревали — шаги
        # ссылались на переименованные процессоры и несуществующие параметры.
        # Проверено на живом сервере БЕЗ env-переменных: 3 роута активны.
        # PluginLoader остаётся выключенным: extensions/ грузятся явно.
        assert s.route_loader_enabled is True
        assert s.extensions_dir == Path("extensions")
        assert s.routes_dir == Path("routes")
        # core_version берётся из метаданных дистрибутива, а не из литерала:
        # раньше здесь стояло "0.2.0", и плагины с requires_core=">=0.20,<0.21"
        # молча помечались как skipped (semver: 0.2.0 < 0.20.0).
        assert s.core_version == _installed_version()
        assert s.core_version != "0.2.0"
        # S162 W6: pybreaker_enabled was removed from PluginLoaderSettings (sibling
        # Sprint 7 cleanup). Canonical location is canonical CB module.

    def test_custom_values(self) -> None:
        s = PluginLoaderSettings(plugin_loader_enabled=True, core_version="1.0.0")
        assert s.plugin_loader_enabled is True
        assert s.core_version == "1.0.0"

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            PluginLoaderSettings(hot_reload_debounce_ms=-1)
