"""Unit-тесты ``services.cache`` — coverage ratchet (Post-Plan A Sprint 2).

core/cache services package facade: re-exports ``UnifiedCacheFacade`` +
``CacheResult`` + ``get_unified_cache_facade`` factory. ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity +
DI factory registration check.
"""

from __future__ import annotations

import pytest

from src.backend.services import cache
from src.backend.services.cache import (
    CacheResult,
    UnifiedCacheFacade,
    get_unified_cache_facade,
)


@pytest.mark.unit
class TestCacheFacadeAllExports:
    """``__all__`` audit + class/function identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["CacheResult", "UnifiedCacheFacade", "get_unified_cache_facade"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(cache, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in cache.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(cache.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает cache services package."""
        assert cache.__doc__ is not None
        assert "Cache" in cache.__doc__


@pytest.mark.unit
class TestCacheFacadeIdentity:
    """Identity checks для re-exports."""

    def test_unified_cache_facade_is_class(self) -> None:
        """``UnifiedCacheFacade`` — class (canonical facade)."""
        assert isinstance(UnifiedCacheFacade, type)

    def test_cache_result_is_class(self) -> None:
        """``CacheResult`` — class (Pydantic/dataclass result type)."""
        assert isinstance(CacheResult, type)

    def test_get_unified_cache_facade_is_callable(self) -> None:
        """``get_unified_cache_facade`` — callable (DI factory)."""
        assert callable(get_unified_cache_facade)

    def test_get_unified_cache_facade_default_plugin(self) -> None:
        """``get_unified_cache_facade`` default plugin='extension'."""
        import inspect

        sig = inspect.signature(get_unified_cache_facade)
        assert "plugin" in sig.parameters
        assert sig.parameters["plugin"].default == "extension"

    def test_get_unified_cache_facade_raises_runtime_error_when_not_registered(self) -> None:
        """``get_unified_cache_facade`` без registered service → RuntimeError (graceful)."""
        from src.backend.core.svcs_registry import has_service

        original_has_service = has_service

        def fake_has_service(svc_type):  # noqa: ARG001
            return False

        import src.backend.core.svcs_registry as registry_module

        try:
            registry_module.has_service = fake_has_service
            with pytest.raises(RuntimeError, match="not registered"):
                get_unified_cache_facade()
        finally:
            registry_module.has_service = original_has_service
