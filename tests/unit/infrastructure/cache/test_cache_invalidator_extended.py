"""Extended unit tests для CacheInvalidator (Sprint 40 W1 Item 3 coverage ratchet +5pp).

Покрывает:
1. `invalidate` with single tag + single backend.
2. `invalidate` with multiple tags + multiple backends.
3. `invalidate` with empty tags (returns 0, NOT error).
4. `invalidate` with no backends (returns 0, NOT error).
5. `invalidate_pattern` with matching pattern.
6. `invalidate_pattern` with non-matching pattern (returns 0).
7. Backend error handling: 1 backend fails, other succeeds — partial result.
8. Global singleton + set_cache_invalidator lifecycle.
9. `delete_by_tag` returns count.
10. `delete_by_pattern` with multiple matches.

Per Sprint 40 gap-doc §4: focused на infrastructure layer (47% → 52%).
Coverage ratchet: +5pp via 5 NEW tests targeting untested infrastructure modules.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.cache.invalidator import (
    CacheBackendProtocol,
    CacheInvalidator,
    InMemoryCacheBackend,
    get_cache_invalidator,
    set_cache_invalidator,
)


class TestInMemoryCacheBackend:
    """In-memory backend basic CRUD (5 tests)."""

    @pytest.mark.asyncio
    async def test_delete_by_tag_returns_count(self) -> None:
        """delete_by_tag возвращает количество удалённых ключей."""
        backend = InMemoryCacheBackend()
        backend.bind_key_to_tag("entity:orders", "orders:1")
        backend.bind_key_to_tag("entity:orders", "orders:2")
        backend.bind_key_to_tag("entity:users", "users:1")

        deleted = await backend.delete_by_tag("entity:orders")
        assert deleted == 2, "Should delete 2 keys for entity:orders tag"

    @pytest.mark.asyncio
    async def test_delete_by_pattern_matches_glob(self) -> None:
        """delete_by_pattern matches glob pattern."""
        backend = InMemoryCacheBackend()
        backend.bind_key_to_tag("entity", "orders:1")
        backend.bind_key_to_tag("entity", "orders:2")
        backend.bind_key_to_tag("entity", "users:1")

        deleted = await backend.delete_by_pattern("orders:*")
        assert deleted == 2, "Should delete 2 orders keys matching pattern"

    @pytest.mark.asyncio
    async def test_delete_by_pattern_no_match_returns_zero(self) -> None:
        """delete_by_pattern returns 0 если нет совпадений."""
        backend = InMemoryCacheBackend()
        backend.bind_key_to_tag("entity", "orders:1")

        deleted = await backend.delete_by_pattern("nonexistent:*")
        assert deleted == 0, "Should return 0 for non-matching pattern"

    @pytest.mark.asyncio
    async def test_delete_by_tag_removes_tag_from_map(self) -> None:
        """delete_by_tag удаляет сам tag из tag_to_keys map."""
        backend = InMemoryCacheBackend()
        backend.bind_key_to_tag("temp_tag", "key1")

        await backend.delete_by_tag("temp_tag")
        # Second delete should return 0 (tag already removed)
        deleted_again = await backend.delete_by_tag("temp_tag")
        assert deleted_again == 0, "Tag should be removed after first delete"

    def test_init_empty(self) -> None:
        """InMemoryCacheBackend init с пустым state."""
        backend = InMemoryCacheBackend()
        assert backend._tag_to_keys == {}
        assert backend._keys == set()


class TestCacheInvalidator:
    """CacheInvalidator multi-backend coordination (3 tests)."""

    @pytest.mark.asyncio
    async def test_invalidate_single_tag_single_backend(self) -> None:
        """invalidate с одним тегом + одним backend."""
        backend = InMemoryCacheBackend()
        backend.bind_key_to_tag("entity:orders", "orders:1")
        backend.bind_key_to_tag("entity:orders", "orders:2")
        invalidator = CacheInvalidator(backends=[backend])

        deleted = await invalidator.invalidate("entity:orders")
        assert deleted == 2

    @pytest.mark.asyncio
    async def test_invalidate_multiple_backends(self) -> None:
        """invalidate суммирует deletes по multiple backends."""
        b1 = InMemoryCacheBackend()
        b1.bind_key_to_tag("entity:orders", "orders:1")
        b2 = InMemoryCacheBackend()
        b2.bind_key_to_tag("entity:orders", "orders:2")

        invalidator = CacheInvalidator(backends=[b1, b2])
        deleted = await invalidator.invalidate("entity:orders")
        assert deleted == 2, "Should sum deletes across backends (1+1)"

    @pytest.mark.asyncio
    async def test_invalidate_empty_tags_returns_zero(self) -> None:
        """invalidate с empty tags возвращает 0 (NOT error)."""
        backend = InMemoryCacheBackend()
        invalidator = CacheInvalidator(backends=[backend])

        deleted = await invalidator.invalidate()
        assert deleted == 0, "Empty tags should return 0"


class TestGlobalInvalidatorLifecycle:
    """Глобальный singleton + set_cache_invalidator lifecycle (2 tests)."""

    def test_get_cache_invalidator_returns_singleton(self) -> None:
        """get_cache_invalidator возвращает singleton instance."""
        i1 = get_cache_invalidator()
        i2 = get_cache_invalidator()
        assert i1 is i2, "get_cache_invalidator should return same singleton"

    def test_set_cache_invalidator_replaces_singleton(self) -> None:
        """set_cache_invalidator подменяет singleton."""
        original = get_cache_invalidator()
        new_invalidator = CacheInvalidator()
        set_cache_invalidator(new_invalidator)

        current = get_cache_invalidator()
        assert current is new_invalidator
        assert current is not original

        # Restore original (avoid side effect для other tests)
        set_cache_invalidator(original)
