"""Unit tests for src.backend.core.interfaces.cache."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.cache import CacheBackend


class TestCacheBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            CacheBackend()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(CacheBackend):
            async def get(self, key: str) -> bytes | None:
                return None

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(CacheBackend):
            async def get(self, key: str) -> bytes | None:
                return None

            async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
                pass

            async def delete(self, *keys: str) -> None:
                pass

            async def delete_pattern(self, pattern: str) -> None:
                pass

            async def exists(self, key: str) -> bool:
                return False

        assert Full() is not None
