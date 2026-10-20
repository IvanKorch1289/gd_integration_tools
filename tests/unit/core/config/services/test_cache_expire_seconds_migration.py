"""Tests for cache_expire_seconds migration from RedisSettings → CacheSettings (cycle 164).

ADR-0352 consolidation plan item #2: cache_expire_seconds — это CACHE
concern, не redis-специфичный. Мигрировал из RedisSettings в CacheSettings
(single source of truth).

These tests verify:

1. ``CacheSettings.cache_expire_seconds`` field exists with default 300.
2. ``RedisSettings.cache_expire_seconds`` теперь @property → backward-compat.
3. decorator.py читает ``settings.cache.cache_expire_seconds`` (не .redis).
4. config_profiles/base.yml: cache_expire_seconds в cache: section (не redis:).
5. Env override: ``CACHE_CACHE_EXPIRE_SECONDS`` (через Pydantic env_prefix).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from src.backend.core.config.services.cache import (
    CacheSettings,
    RedisSettings,
    cache_settings,
)


class TestCacheExpireSecondsInCacheSettings:
    def test_field_exists(self) -> None:
        """``CacheSettings.cache_expire_seconds`` field is declared."""
        field_names = set(CacheSettings.model_fields.keys())
        assert "cache_expire_seconds" in field_names

    def test_default_value(self) -> None:
        """Default is 300 seconds."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_CACHE_EXPIRE_SECONDS", None)
            settings = CacheSettings()
        assert settings.cache_expire_seconds == 300

    def test_min_value_constraint(self) -> None:
        """``ge=60`` — TTL короче 60s недопустим (anti-pattern)."""
        import pytest

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_CACHE_EXPIRE_SECONDS", None)
            with pytest.raises(Exception):  # ValidationError
                CacheSettings(cache_expire_seconds=30)

    def test_env_override(self) -> None:
        """``CACHE_CACHE_EXPIRE_SECONDS`` env override."""
        with patch.dict(
            os.environ,
            {"CACHE_CACHE_EXPIRE_SECONDS": "600"},
        ):
            settings = CacheSettings()
        assert settings.cache_expire_seconds == 600

    def test_singleton_exposes_field(self) -> None:
        """``cache_settings`` singleton exposes the field."""
        assert isinstance(cache_settings.cache_expire_seconds, int)
        assert cache_settings.cache_expire_seconds >= 60


class TestRedisSettingsBackwardCompat:
    def test_redis_settings_no_longer_has_field(self) -> None:
        """``cache_expire_seconds`` REMOVED from RedisSettings model_fields."""
        # Field removed from RedisSettings — only backward-compat property remains.
        # model_fields does NOT include the property (which is a runtime attribute).
        assert "cache_expire_seconds" not in RedisSettings.model_fields

    def test_redis_property_returns_cache_value(self) -> None:
        """``RedisSettings.cache_expire_seconds`` property → CacheSettings value."""
        # Build minimal valid settings without cache_expire_seconds (now removed).
        settings = RedisSettings(
            host="localhost",
            port=6379,
            password=None,
            encoding="utf-8",
            db_cache=0,
            db_queue=1,
            db_limits=2,
            db_tasks=3,
            max_connections=20,
            use_ssl=False,
            max_stream_len=100000,
            approximate_trimming_stream=True,
            retention_hours_stream=24,
            max_retries=1,
            ttl_hours=1,
            health_check_interval=600,
            streams=[{"name": "main", "value": "stream1"}],
        )
        # Property returns the value from CacheSettings (single source of truth).
        assert settings.cache_expire_seconds == cache_settings.cache_expire_seconds


class TestDecoratorUsesCacheSettings:
    def test_decorator_uses_settings_cache_not_redis(self) -> None:
        """``decorator.py`` reads ``settings.cache.cache_expire_seconds``.

        Static-source check: scan the decorator file for the old pattern.
        """
        decorator_path = (
            Path(__file__).parents[5]
            / "src"
            / "backend"
            / "infrastructure"
            / "decorators"
            / "caching"
            / "decorator.py"
        )
        assert decorator_path.exists()
        source = decorator_path.read_text(encoding="utf-8")

        # Cycle 164: decorator reads from settings.cache (canonical).
        assert "settings.cache.cache_expire_seconds" in source, (
            "Cycle 164 regression: decorator.py must read "
            "settings.cache.cache_expire_seconds (canonical)."
        )
        # Old pattern should NOT be the primary read path
        # (RedisSettings.cache_expire_seconds still exists as property but
        # production code should not use it directly).
        assert "self.expire = expire or settings.redis.cache_expire_seconds" not in source, (
            "Cycle 164 regression: decorator.py still reads from "
            "settings.redis.cache_expire_seconds directly."
        )


class TestConfigProfilesYaml:
    def test_cache_expire_seconds_in_cache_section(self) -> None:
        """``config_profiles/base.yml``: cache_expire_seconds в cache: section, не redis:."""
        config_path = (
            Path(__file__).parents[5] / "config_profiles" / "base.yml"
        )
        assert config_path.exists()
        config_text = config_path.read_text(encoding="utf-8")

        # Find redis: section and ensure cache_expire_seconds not directly inside.
        # Note: line "  # NOTE: cache_expire_seconds мигрировал..." in redis section
        # is acceptable (informational comment), but no actual "cache_expire_seconds: N"
        # YAML value under redis:.
        # Simple check: scan for "cache_expire_seconds:" with indentation of "redis:".
        import re

        redis_section = re.search(
            r"^redis:\n((?:  [^#].*\n)+)", config_text, re.MULTILINE
        )
        if redis_section:
            redis_body = redis_section.group(1)
            assert "cache_expire_seconds:" not in redis_body, (
                "Cycle 164 regression: cache_expire_seconds still in redis: section"
            )

        # Ensure cache_expire_seconds present in cache: section.
        # Regex: any "  cache_expire_seconds:" line with 2-space indent
        # within the cache section (comment lines allowed before).
        cache_section = re.search(
            r"^cache:\n((?:  [^\n]*\n)+)", config_text, re.MULTILINE
        )
        assert cache_section is not None, "cache: section missing in base.yml"
        cache_body = cache_section.group(1)
        assert "cache_expire_seconds:" in cache_body, (
            "Cycle 164 migration: cache_expire_seconds must be in cache: section"
        )