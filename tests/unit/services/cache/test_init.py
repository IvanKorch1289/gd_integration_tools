"""Tests for services/cache/__init__.py (S100 — coverage push).

get_unified_cache_facade factory + re-exports.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_module_dunder_all() -> None:
    """__all__ = ('CacheResult', 'UnifiedCacheFacade', 'get_unified_cache_facade')."""
    import src.backend.services.cache as mod

    assert mod.__all__ == (
        "CacheResult",
        "UnifiedCacheFacade",
        "get_unified_cache_facade",
    )


def test_cache_result_importable() -> None:
    """CacheResult re-exported from facade."""
    from src.backend.services.cache import CacheResult

    assert CacheResult is not None


def test_unified_cache_facade_importable() -> None:
    """UnifiedCacheFacade re-exported."""
    from src.backend.services.cache import UnifiedCacheFacade

    assert UnifiedCacheFacade is not None


def test_get_unified_cache_facade_extension_path() -> None:
    """get_unified_cache_facade(plugin='extension') → returns registered facade."""
    from src.backend.services.cache import get_unified_cache_facade

    fake_facade = MagicMock()
    with patch("src.backend.core.svcs_registry.has_service", return_value=True), patch(
        "src.backend.core.svcs_registry.get_service", return_value=fake_facade
    ):
        result = get_unified_cache_facade(plugin="extension")
    assert result is fake_facade


def test_get_unified_cache_facade_non_extension_returns_new_instance() -> None:
    """get_unified_cache_facade(plugin=non-default) → new UnifiedCacheFacade instance."""
    from src.backend.services.cache import UnifiedCacheFacade, get_unified_cache_facade

    fake_facade = MagicMock()
    fake_facade._primary = MagicMock()
    fake_facade._memory = MagicMock()
    fake_facade._disk = MagicMock()
    fake_facade._check = MagicMock()

    with patch("src.backend.core.svcs_registry.has_service", return_value=True), patch(
        "src.backend.core.svcs_registry.get_service", return_value=fake_facade
    ):
        result = get_unified_cache_facade(plugin="my_plugin")

    assert isinstance(result, UnifiedCacheFacade)
    assert result._plugin == "my_plugin"


def test_get_unified_cache_facade_raises_when_not_registered() -> None:
    """get_unified_cache_facade → RuntimeError если facade не зарегистрирован."""
    import pytest
    from src.backend.services.cache import get_unified_cache_facade

    with patch("src.backend.core.svcs_registry.has_service", return_value=False):
        with pytest.raises(RuntimeError, match="not registered"):
            get_unified_cache_facade()
