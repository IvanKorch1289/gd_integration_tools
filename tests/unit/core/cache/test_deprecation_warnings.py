"""Tests for Stage 3 deprecation warnings (ADR-0352 cycle 166).

Cycle 166: ``MemoryCacheFacade``, ``FallbackCacheFacade``, ``RedisCacheFacade``
(``core.cache.facade``) помечены ``DeprecationWarning``. Будет удалены в
cycle 167 (Stage 4).

These tests verify:
1. Deprecation warnings issued при instantiation.
2. Warning message содержит migration hint.
3. ABC ``UnifiedCacheFacade`` остаётся canonical (НЕ помечен deprecated).
4. Services facade ``UnifiedCacheFacade`` НЕ помечен deprecated.
"""

from __future__ import annotations

import warnings

import pytest


class TestCoreFacadeDeprecationWarnings:
    """Cycle 166: core-facade concrete impls должны emit DeprecationWarning."""

    def test_memory_cache_facade_warns(self) -> None:
        """``MemoryCacheFacade()`` emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.core.cache.facade import MemoryCacheFacade

            MemoryCacheFacade()

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 1
            msg = str(deprecation_warnings[0].message)
            assert "MemoryCacheFacade" in msg
            assert "DEPRECATED" in msg
            assert "cycle 166" in msg
            assert "cycle 167" in msg
            # Migration hint
            assert (
                "src.backend.services.cache.UnifiedCacheFacade" in msg
                or "src.backend.core.di.providers.cache.get_cache_facade" in msg
            )

    def test_fallback_cache_facade_warns(self) -> None:
        """``FallbackCacheFacade(primary, fallback)`` emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.core.cache.facade import (
                FallbackCacheFacade,
                MemoryCacheFacade,
            )

            m = MemoryCacheFacade()
            FallbackCacheFacade(primary=m, fallback=m)

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 2
            # Both MemoryCacheFacade + FallbackCacheFacade warnings.
            messages = [str(x.message) for x in deprecation_warnings]
            assert any("MemoryCacheFacade" in m for m in messages)
            assert any("FallbackCacheFacade" in m for m in messages)

    def test_redis_cache_facade_warns(self) -> None:
        """``RedisCacheFacade(backend)`` emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.core.cache.facade import RedisCacheFacade

            class _StubBackend:
                async def get(self, key):
                    return None

                async def set(self, key, value, ttl=None):
                    pass

                async def delete(self, *keys):
                    pass

                async def delete_by_tag(self, tag):
                    return 0

                async def exists(self, key):
                    return False

            RedisCacheFacade(backend=_StubBackend())

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 1
            assert "RedisCacheFacade" in str(deprecation_warnings[0].message)


class TestUnifiedCacheFacadeNotDeprecated:
    """ABC ``UnifiedCacheFacade`` (core) — NOT deprecated (canonical interface)."""

    def test_abc_class_definition_not_warn(self) -> None:
        """``UnifiedCacheFacade`` ABC не должен emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.core.cache.facade import (
                UnifiedCacheFacade as CoreABC,
            )

            # ABC import + reference shouldn't emit DeprecationWarning.
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
                and "src.backend.core.cache.facade" in str(x.message)
            ]
            assert deprecation_warnings == []


class TestServicesFacadeNotDeprecated:
    """Services facade ``UnifiedCacheFacade`` — NOT deprecated (production canonical)."""

    def test_services_class_definition_not_warn(self) -> None:
        """``services.cache.UnifiedCacheFacade`` не должен emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.services.cache.facade import (
                UnifiedCacheFacade as ServicesFacade,
            )

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
                and "src.backend.services.cache" in str(x.message)
            ]
            assert deprecation_warnings == []


class TestMigrationGuideExists:
    """ADR-0352.1 — migration guide for core-facade → services-facade."""

    def test_migration_guide_file_exists(self) -> None:
        """``docs/adr/0352.1-cache-facade-migration-guide.md`` exists."""
        from pathlib import Path

        guide = (
            Path(__file__).parents[4]
            / "docs"
            / "adr"
            / "0352.1-cache-facade-migration-guide.md"
        )
        assert guide.exists(), f"Migration guide not found at {guide}"

    def test_migration_guide_content(self) -> None:
        """Migration guide covers OLD/NEW patterns."""
        from pathlib import Path

        guide_path = (
            Path(__file__).parents[4]
            / "docs"
            / "adr"
            / "0352.1-cache-facade-migration-guide.md"
        )
        content = guide_path.read_text(encoding="utf-8")

        # Required sections.
        assert "TL;DR" in content
        assert "Migration patterns" in content
        assert "API mapping" in content or "mapping" in content
        # Key migration targets.
        assert "MemoryCacheFacade" in content
        assert "FallbackCacheFacade" in content
        assert "RedisCacheFacade" in content
        # Canonical replacement.
        assert "UnifiedCacheFacade" in content
        assert "services.cache" in content
        # Timeline.
        assert "Stage 2" in content
        assert "Stage 3" in content
        assert "Stage 4" in content