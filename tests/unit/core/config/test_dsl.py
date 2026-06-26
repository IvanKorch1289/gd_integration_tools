"""Tests for src.backend.core.config.dsl."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.dsl import DSLSettings


class TestDSLSettings:
    def test_defaults(self) -> None:
        s = DSLSettings()
        assert s.routes_dir == Path("dsl_routes")
        assert s.hot_reload_enabled is False  # default-OFF feature flag
        assert s.hot_reload_debounce_ms == 500

    def test_custom_values(self) -> None:
        s = DSLSettings(
            routes_dir=Path("routes"),
            hot_reload_enabled=True,
            hot_reload_debounce_ms=1000,
        )
        assert s.routes_dir == Path("routes")
        assert s.hot_reload_enabled is True
        assert s.hot_reload_debounce_ms == 1000

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            DSLSettings(hot_reload_debounce_ms=-1)
        with pytest.raises(Exception):
            DSLSettings(hot_reload_debounce_ms=20_000)
