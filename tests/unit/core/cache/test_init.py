"""Unit-тесты ``core.cache`` — coverage ratchet (S48 W28).

core/cache/__init__.py — S165 W1 / S171 M28 D293 facade: re-exports
canonical cache primitives (UnifiedCacheFacade ABC + MemoryCacheFacade +
FallbackCacheFacade + CacheInvalidationPolicy + CacheError + ThreeTierRagCache)
для extensions/SDK consumers без reaching в cache.facade / cache.rag submodules.
9 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + ABC check.
"""

from __future__ import annotations

import pytest

from src.backend.core import cache as core_cache
from src.backend.core.cache import (
    CacheError,
    CacheInvalidationPolicy,
    FallbackCacheFacade,
    MemoryCacheFacade,
    ThreeTierRagCache,
    UnifiedCacheFacade,
)


@pytest.mark.unit
class TestCacheFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "CacheError",
            "CacheInvalidationPolicy",
            "FallbackCacheFacade",
            "MemoryCacheFacade",
            "ThreeTierRagCache",
            "UnifiedCacheFacade",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(core_cache, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in core_cache.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 6 символов."""
        assert len(core_cache.__all__) == 6

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S165 W1 / S171 M28 D293 facade."""
        assert core_cache.__doc__ is not None
        assert "S165" in core_cache.__doc__ or "S171" in core_cache.__doc__


@pytest.mark.unit
class TestCacheFacadeIdentity:
    """Identity checks: ABC + Pydantic policy + exception."""

    def test_unified_cache_facade_is_abc(self) -> None:
        """``UnifiedCacheFacade`` — ABC (Abstract Base Class)."""
        from abc import ABC

        assert issubclass(UnifiedCacheFacade, ABC)

    def test_memory_cache_facade_implements_abc(self) -> None:
        """``MemoryCacheFacade`` — concrete impl of UnifiedCacheFacade ABC."""
        assert issubclass(MemoryCacheFacade, UnifiedCacheFacade)

    def test_fallback_cache_facade_implements_abc(self) -> None:
        """``FallbackCacheFacade`` — concrete impl of UnifiedCacheFacade ABC."""
        assert issubclass(FallbackCacheFacade, UnifiedCacheFacade)

    def test_three_tier_rag_cache_is_class(self) -> None:
        """``ThreeTierRagCache`` — class (RAG 3-tier L1/L2/L3)."""
        assert isinstance(ThreeTierRagCache, type)

    def test_cache_invalidation_policy_is_class(self) -> None:
        """``CacheInvalidationPolicy`` — class (Pydantic policy)."""
        assert isinstance(CacheInvalidationPolicy, type)

    def test_cache_error_is_exception(self) -> None:
        """``CacheError`` — exception class (subclass of Exception)."""
        assert issubclass(CacheError, Exception)
