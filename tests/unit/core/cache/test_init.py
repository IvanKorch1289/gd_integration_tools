"""Unit-тесты ``core.cache`` — coverage ratchet (S48 W28 + cycle 167).

Cycle 167 (ADR-0352 Stage 4): concrete impls REMOVED из core.cache.facade.
``core/cache/__init__.py`` re-exports canonical: UnifiedCacheFacade ABC +
CacheError + CacheInvalidationPolicy + ThreeTierRagCache (4 symbols,
down from 6).

Цель slice: 0% → 100% через __all__ audit + class identity + ABC check.
"""

from __future__ import annotations

import pytest

from src.backend.core import cache as core_cache
from src.backend.core.cache import (
    CacheError,
    CacheInvalidationPolicy,
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
            "ThreeTierRagCache",
            "UnifiedCacheFacade",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(core_cache, symbol_name), f"Missing export: {symbol_name}"
        assert symbol_name in core_cache.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа (down from 6 — cycle 167 REMOVE)."""
        assert len(core_cache.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает cycle 167 / Stage 4."""
        assert core_cache.__doc__ is not None
        assert (
            "S165" in core_cache.__doc__
            or "S171" in core_cache.__doc__
            or "Cycle 167" in core_cache.__doc__
        )

    def test_deprecated_concrete_impls_not_exported(self) -> None:
        """Cycle 167 (Stage 4): MemoryCacheFacade/FallbackCacheFacade/RedisCacheFacade
        НЕ в ``__all__``.
        """
        for name in ("MemoryCacheFacade", "FallbackCacheFacade", "RedisCacheFacade"):
            assert name not in core_cache.__all__, (
                f"{name} should NOT be in core.cache.__all__ (Stage 4 REMOVE)"
            )


@pytest.mark.unit
class TestCacheFacadeIdentity:
    """Identity checks: ABC + Pydantic policy + exception."""

    def test_unified_cache_facade_is_abc(self) -> None:
        """``UnifiedCacheFacade`` — ABC (Abstract Base Class)."""
        from abc import ABC

        assert issubclass(UnifiedCacheFacade, ABC)

    def test_three_tier_rag_cache_is_class(self) -> None:
        """``ThreeTierRagCache`` — class (RAG 3-tier L1/L2/L3)."""
        assert isinstance(ThreeTierRagCache, type)

    def test_cache_invalidation_policy_is_class(self) -> None:
        """``CacheInvalidationPolicy`` — class (Pydantic policy)."""
        assert isinstance(CacheInvalidationPolicy, type)

    def test_cache_error_is_exception(self) -> None:
        """``CacheError`` — exception class (subclass of Exception)."""
        assert issubclass(CacheError, Exception)


@pytest.mark.unit
class TestCacheFacadeCanonicalUnchanged:
    """Cycle 167: ABC остаётся canonical, не помечается deprecated."""

    def test_unified_cache_facade_abstract_methods(self) -> None:
        """ABC имеет abstract methods после Stage 4 REMOVE."""
        abstract_methods = UnifiedCacheFacade.__abstractmethods__
        assert "get" in abstract_methods
        assert "set" in abstract_methods
        assert "delete" in abstract_methods
        assert "delete_by_tag" in abstract_methods
        assert "exists" in abstract_methods
        assert "healthcheck" in abstract_methods

    def test_unified_cache_facade_has_policy(self) -> None:
        """ABC имеет ``policy: ClassVar[CacheInvalidationPolicy]``."""
        assert hasattr(UnifiedCacheFacade, "policy")
        assert isinstance(UnifiedCacheFacade.policy, CacheInvalidationPolicy)