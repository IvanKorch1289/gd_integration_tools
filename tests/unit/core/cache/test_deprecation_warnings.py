"""Tests for Stage 4 REMOVE verification (ADR-0352 cycle 167).

Cycle 167: ``MemoryCacheFacade``, ``FallbackCacheFacade``, ``RedisCacheFacade``
(``core.cache.facade``) REMOVED из core. Import попытки должны fail с
``ImportError`` (НЕ ``DeprecationWarning``).

Tests verify:
1. ``MemoryCacheFacade`` не импортируется — ``ImportError``.
2. ``FallbackCacheFacade`` не импортируется — ``ImportError``.
3. ``RedisCacheFacade`` не импортируется — ``ImportError``.
4. ABC ``UnifiedCacheFacade`` остаётся canonical.
5. Services facade ``UnifiedCacheFacade`` остаётся production canonical.
6. Migration guide ADR-0352.1 существует и содержит Stage 4 removal note.
"""

from __future__ import annotations

import pytest


class TestCoreFacadeConcreteImplsRemoved:
    """Cycle 167 (Stage 4): concrete impls REMOVED — ImportError."""

    def test_memory_cache_facade_import_raises(self) -> None:
        """``from core.cache.facade import MemoryCacheFacade`` → ImportError."""
        with pytest.raises(ImportError):
            exec(  # noqa: S102
                "from src.backend.core.cache.facade import MemoryCacheFacade"
            )

    def test_fallback_cache_facade_import_raises(self) -> None:
        """``from core.cache.facade import FallbackCacheFacade`` → ImportError."""
        with pytest.raises(ImportError):
            exec(  # noqa: S102
                "from src.backend.core.cache.facade import FallbackCacheFacade"
            )

    def test_redis_cache_facade_import_raises(self) -> None:
        """``from core.cache.facade import RedisCacheFacade`` → ImportError."""
        with pytest.raises(ImportError):
            exec(  # noqa: S102
                "from src.backend.core.cache.facade import RedisCacheFacade"
            )

    def test_disk_cache_facade_import_raises(self) -> None:
        """``from core.cache.facade import DiskCacheFacade`` → ImportError (cycle 164 REMOVE)."""
        with pytest.raises(ImportError):
            exec(  # noqa: S102
                "from src.backend.core.cache.facade import DiskCacheFacade"
            )

    def test_concrete_impls_not_in_core_cache_all(self) -> None:
        """Deprecated concrete impls НЕ в ``src.backend.core.cache.__all__``."""
        from src.backend.core.cache import __all__

        for name in (
            "MemoryCacheFacade",
            "FallbackCacheFacade",
            "RedisCacheFacade",
            "DiskCacheFacade",
        ):
            assert name not in __all__, (
                f"{name} should NOT be in core.cache.__all__ (Stage 4 REMOVE)"
            )


class TestUnifiedCacheFacadeCanonicalUnchanged:
    """ABC ``UnifiedCacheFacade`` (core) — NOT deprecated, NOT removed."""

    def test_abc_class_definition_works(self) -> None:
        """``UnifiedCacheFacade`` ABC importable, no warnings."""
        import warnings

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.core.cache.facade import (
                UnifiedCacheFacade as CoreABC,
            )

            assert CoreABC is not None
        # No DeprecationWarning for ABC.
        deprecation_warnings = [
            r for r in record if issubclass(r.category, DeprecationWarning)
        ]
        assert deprecation_warnings == []


class TestServicesFacadeCanonicalUnchanged:
    """Services facade ``UnifiedCacheFacade`` — NOT deprecated, NOT removed."""

    def test_services_class_definition_works(self) -> None:
        """``services.cache.UnifiedCacheFacade`` importable, no warnings."""
        import warnings

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always", DeprecationWarning)
            from src.backend.services.cache.facade import (
                UnifiedCacheFacade as ServicesFacade,
            )

            assert ServicesFacade is not None
        deprecation_warnings = [
            r for r in record if issubclass(r.category, DeprecationWarning)
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

    def test_migration_guide_documents_stage_4_removal(self) -> None:
        """Migration guide covers Stage 4 REMOVE."""
        from pathlib import Path

        guide_path = (
            Path(__file__).parents[4]
            / "docs"
            / "adr"
            / "0352.1-cache-facade-migration-guide.md"
        )
        content = guide_path.read_text(encoding="utf-8")

        # Stage 4 sections.
        assert "Stage 4" in content
        assert "REMOVE" in content
        # Timeline with all 4 cycles.
        assert "165" in content
        assert "166" in content
        assert "167" in content
        # Migration targets.
        assert "MemoryCacheFacade" in content
        assert "FallbackCacheFacade" in content
        assert "RedisCacheFacade" in content
        # Canonical replacement.
        assert "UnifiedCacheFacade" in content
        assert "services.cache" in content

    def test_migration_guide_removed_classes_warning(self) -> None:
        """Migration guide documents that classes are REMOVED in Stage 4."""
        from pathlib import Path

        guide_path = (
            Path(__file__).parents[4]
            / "docs"
            / "adr"
            / "0352.1-cache-facade-migration-guide.md"
        )
        content = guide_path.read_text(encoding="utf-8")

        # Warning text mentions Stage 4 removal.
        assert (
            "Will be removed" in content or "Stage 4" in content
        ), "Migration guide must document Stage 4 REMOVE"


class TestFilterWarningsForBackwardCompat:
    """Cycle 167 (Stage 4 REMOVE): stale filterwarnings pattern removed.

    Cycle 166 (Stage 3) added DeprecationWarning + filterwarnings pattern.
    Cycle 167 (Stage 4) REMOVED classes — pattern now stale (no more
    warnings emitted). Pattern удалён из ``pyproject.toml``.
    """

    def test_filterwarnings_pattern_removed(self) -> None:
        """Cycle 167: filterwarnings pattern для core-facade REMOVED.

        Pattern from cycle 166 is now stale (no DeprecationWarning emitted
        since classes are REMOVED). Test verifies removal.
        """
        from pathlib import Path

        pyproject = (
            Path(__file__).parents[4] / "pyproject.toml"
        )
        content = pyproject.read_text(encoding="utf-8")
        # Pattern was added cycle 166, removed cycle 167.
        # Verify it is NOT in pyproject.toml anymore.
        assert (
            "src.backend.core.cache.facade" not in content
            or "Stage 4 REMOVE" in content  # documentation reference is OK
        ), (
            "Cycle 167: filterwarnings pattern for core-facade should be "
            "REMOVED (classes are gone, no DeprecationWarning emitted)"
        )