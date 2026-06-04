"""Tests for src.backend.core.config.v11."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.v11 import V11Settings


class TestV11Settings:
    def test_defaults(self) -> None:
        s = V11Settings()
        assert s.plugin_loader_enabled is False
        assert s.route_loader_enabled is False
        assert s.extensions_dir == Path("extensions")
        assert s.routes_dir == Path("routes")
        assert s.core_version == "0.2.0"
        assert s.pybreaker_enabled is False

    def test_custom_values(self) -> None:
        s = V11Settings(plugin_loader_enabled=True, core_version="1.0.0")
        assert s.plugin_loader_enabled is True
        assert s.core_version == "1.0.0"

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            V11Settings(hot_reload_debounce_ms=-1)
