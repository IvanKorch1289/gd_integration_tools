"""Tests for CacheSettings.disk_fallback_path + disk_fallback_enabled (cycle 163).

Cycle 163 cache audit found: ``service_setup.py::_register_cache_facade``
resolved ``disk_fallback_path`` via ``getattr(cache_settings, ..., None)`` —
a field that didn't exist in ``CacheSettings``. This hid the gap and
DEFP-вred hardcoded ``Path("var/cache/disk_fallback")`` in composition root.

These tests verify:

1. The field IS now present in ``CacheSettings``.
2. ``disk_fallback_enabled`` is present and defaults to True.
3. Values can be overridden via env vars (``CACHE_DISK_FALLBACK_PATH``,
   ``CACHE_DISK_FALLBACK_ENABLED``).
4. The existing ``cache_settings`` singleton exposes both fields.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from src.backend.core.config.services.cache import (
    CacheSettings,
    cache_settings,
)


class TestDiskFallbackFieldExists:
    def test_disk_fallback_path_field_exists(self) -> None:
        """CacheSettings declares ``disk_fallback_path``."""
        field_names = set(CacheSettings.model_fields.keys())
        assert "disk_fallback_path" in field_names

    def test_disk_fallback_enabled_field_exists(self) -> None:
        """CacheSettings declares ``disk_fallback_enabled``."""
        field_names = set(CacheSettings.model_fields.keys())
        assert "disk_fallback_enabled" in field_names


class TestDiskFallbackDefaults:
    def test_disk_fallback_path_default(self) -> None:
        """Default ``disk_fallback_path`` matches the previous hard-coded value."""
        # Use isolated env (no overrides) to check defaults.
        with patch.dict(os.environ, {}, clear=False):
            for key in (
                "CACHE_DISK_FALLBACK_PATH",
                "CACHE_DISK_FALLBACK_ENABLED",
            ):
                os.environ.pop(key, None)
            settings = CacheSettings()
        assert settings.disk_fallback_path == "var/cache/disk_fallback"

    def test_disk_fallback_enabled_default_true(self) -> None:
        """Default ``disk_fallback_enabled`` is True (cycle 163: backward-compat)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_DISK_FALLBACK_ENABLED", None)
            settings = CacheSettings()
        assert settings.disk_fallback_enabled is True


class TestDiskFallbackEnvOverride:
    def test_disk_fallback_path_env_override(self) -> None:
        """CACHE_DISK_FALLBACK_PATH overrides the default path."""
        with patch.dict(
            os.environ,
            {"CACHE_DISK_FALLBACK_PATH": "/tmp/test_cache"},
        ):
            settings = CacheSettings()
        assert settings.disk_fallback_path == "/tmp/test_cache"

    def test_disk_fallback_enabled_env_override(self) -> None:
        """CACHE_DISK_FALLBACK_ENABLED=False disables L3."""
        with patch.dict(
            os.environ,
            {"CACHE_DISK_FALLBACK_ENABLED": "false"},
        ):
            settings = CacheSettings()
        assert settings.disk_fallback_enabled is False


class TestSingletonExposesFields:
    def test_singleton_disk_fallback_path_is_str(self) -> None:
        """The module-level singleton exposes ``disk_fallback_path`` as str."""
        assert isinstance(cache_settings.disk_fallback_path, str)
        assert len(cache_settings.disk_fallback_path) > 0

    def test_singleton_disk_fallback_enabled_is_bool(self) -> None:
        """The module-level singleton exposes ``disk_fallback_enabled`` as bool."""
        assert isinstance(cache_settings.disk_fallback_enabled, bool)

    def test_getattr_no_longer_needed(self) -> None:
        """``getattr(cache_settings, 'disk_fallback_path', None)`` returns the value
        (not None fallback). This is the regression test for the cycle 163 audit.
        """
        # This is exactly the pattern that existed in service_setup.py before
        # the fix. After the fix, getattr is no longer needed; the field is
        # always defined. We just assert the value is present.
        value = getattr(cache_settings, "disk_fallback_path", None)
        assert value is not None, (
            "Cycle 163 regression: getattr fallback must not return None "
            "after disk_fallback_path was added to CacheSettings."
        )

    def test_service_setup_no_getattr(self) -> None:
        """Verify ``service_setup.py`` no longer uses ``getattr`` for these fields.

        Static-source check: scan the file for the old getattr pattern.
        """
        from pathlib import Path

        # __file__ = tests/unit/core/config/services/test_cache_disk_fallback_settings.py
        # parents[0] = services, [1] = config, [2] = core, [3] = unit, [4] = tests
        # We need repo root.
        setup_path = (
            Path(__file__).parents[5]
            / "src"
            / "backend"
            / "plugins"
            / "composition"
            / "service_setup.py"
        )
        assert setup_path.exists(), f"service_setup.py not found at {setup_path}"
        source = setup_path.read_text(encoding="utf-8")
        # The old getattr pattern was:
        #   getattr(cache_settings, "disk_fallback_path", None)
        # After the fix, this should be a direct attribute access.
        assert (
            'getattr(cache_settings, "disk_fallback_path"' not in source
        ), "Cycle 163 regression: service_setup.py still uses getattr fallback."
        # The field should be referenced directly.
        assert (
            "cache_settings.disk_fallback_path" in source
        ), "service_setup.py must read disk_fallback_path directly."