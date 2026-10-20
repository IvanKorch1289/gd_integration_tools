"""Cycle 168 tests: ``get_cache_facade`` ABC contract (PROD_READINESS §1.7).

Раньше ``enable_fallback=False`` игнорировался (memory в обеих ветках).
Cycle 168: ``False`` → ``None``, ``True`` → ``MemoryBackend``.
"""

from __future__ import annotations

from src.backend.core.di.providers.cache import get_cache_facade
from src.backend.infrastructure.cache.backends.memory import MemoryBackend


class TestGetCacheFacade:
    def test_default_returns_memory_backend(self) -> None:
        """``get_cache_facade()`` (default ``enable_fallback=True``) → ``MemoryBackend``."""
        result = get_cache_facade()
        assert isinstance(result, MemoryBackend)

    def test_enable_fallback_true_returns_memory_backend(self) -> None:
        """``enable_fallback=True`` → ``MemoryBackend``."""
        result = get_cache_facade(enable_fallback=True)
        assert isinstance(result, MemoryBackend)

    def test_enable_fallback_false_returns_none(self) -> None:
        """Cycle 168: ``enable_fallback=False`` → ``None`` (primary-only path).

        До cycle 168 этот параметр игнорировался (``memory`` в обоих
        ветках). Теперь поведение согласовано с documented intent.
        """
        result = get_cache_facade(enable_fallback=False)
        assert result is None

    def test_returns_object_without_unified_cache_facade_methods(self) -> None:
        """MemoryBackend НЕ реализует ``delete_by_tag`` и ``healthcheck``.

        Это документированное ограничение — production canonical —
        ``services.cache.UnifiedCacheFacade``, не этот dev/test helper.
        """
        result = get_cache_facade()
        assert not hasattr(result, "delete_by_tag")
        assert not hasattr(result, "healthcheck")