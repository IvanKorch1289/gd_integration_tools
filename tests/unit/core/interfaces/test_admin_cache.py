"""Unit tests for src.backend.core.interfaces.admin_cache."""

from __future__ import annotations

from src.backend.core.interfaces.admin_cache import (
    AdminCacheStorageProtocol,
    CacheInvalidatorProtocol,
)


class TestCacheInvalidatorProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def invalidate(self, *tags: str) -> int:
                return 0

        assert isinstance(Fake(), CacheInvalidatorProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), CacheInvalidatorProtocol)


class TestAdminCacheStorageProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def list_cache_keys(self, pattern: str = "*") -> object:
                return []

            async def get_cache_value(self, key: str) -> object:
                return None

            async def invalidate_cache(self) -> object:
                return None

        assert isinstance(Fake(), AdminCacheStorageProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            async def list_cache_keys(self, pattern: str = "*") -> object:
                return []

        assert not isinstance(Bad(), AdminCacheStorageProtocol)
