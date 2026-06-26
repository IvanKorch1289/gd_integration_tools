"""Tests for src.backend.core.config.v11."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.v11 import PluginLoaderSettings


class TestPluginLoaderSettings:
    def test_defaults(self) -> None:
        s = PluginLoaderSettings()
        assert s.plugin_loader_enabled is False
        assert s.route_loader_enabled is False
        assert s.extensions_dir == Path("extensions")
        assert s.routes_dir == Path("routes")
        assert s.core_version == "0.2.0"
        # S162 W6: pybreaker_enabled was removed from PluginLoaderSettings (sibling
        # Sprint 7 cleanup). Canonical location is canonical CB module.

    def test_custom_values(self) -> None:
        s = PluginLoaderSettings(plugin_loader_enabled=True, core_version="1.0.0")
        assert s.plugin_loader_enabled is True
        assert s.core_version == "1.0.0"

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            PluginLoaderSettings(hot_reload_debounce_ms=-1)
