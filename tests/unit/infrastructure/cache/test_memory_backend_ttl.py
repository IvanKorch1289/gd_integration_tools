"""Cycle 168 tests: ``MemoryBackend`` per-key TTL через entry wrapper.

PROD_READINESS_LOGGING_CACHE_2026-10-20 §1.3: до cycle 168 ``set()``
игнорировал ``ttl`` параметр (использовал global ``TTLCache.ttl``),
что нарушало cache stampede protection (ADR-0051).
"""

from __future__ import annotations

import asyncio

from src.backend.infrastructure.cache.backends.memory import MemoryBackend


class TestMemoryBackendTTL:
    async def test_set_with_ttl_returns_value(self) -> None:
        """set(..., ttl=N) → значение читается до истечения."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=60)
        assert await backend.get("k1") == b"v1"

    async def test_per_key_ttl_expiry(self) -> None:
        """Per-key TTL короче default_ttl → значение истекает раньше."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=1)
        await asyncio.sleep(1.2)
        assert await backend.get("k1") is None

    async def test_ttl_none_uses_default(self) -> None:
        """set(..., ttl=None) → используется default_ttl."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=None)
        await asyncio.sleep(0.5)
        # default_ttl=3600 — значение всё ещё здесь
        assert await backend.get("k1") == b"v1"

    async def test_explicit_ttl_overrides_default(self) -> None:
        """Явный ``ttl=60`` переопределяет default_ttl=3600."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=60)
        # Через 0.1s значение всё ещё здесь (60s TTL)
        await asyncio.sleep(0.1)
        assert await backend.get("k1") == b"v1"

    async def test_exists_respects_ttl(self) -> None:
        """``exists`` возвращает ``False`` для expired entries."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=1)
        assert await backend.exists("k1") is True
        await asyncio.sleep(1.2)
        assert await backend.exists("k1") is False

    async def test_get_removes_expired_entry(self) -> None:
        """Lazy cleanup: expired entry удаляется при get()."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=1)
        await asyncio.sleep(1.2)
        # После get() entry должен быть удалён
        result = await backend.get("k1")
        assert result is None
        # exists должен вернуть False
        assert await backend.exists("k1") is False

    async def test_concurrent_set_get_no_race(self) -> None:
        """Race: set и get под asyncio.Lock — нет inconsistent state."""
        backend = MemoryBackend(maxsize=100, default_ttl=3600)

        async def setter(key: str, value: bytes, ttl: int) -> None:
            await backend.set(key, value, ttl=ttl)

        async def getter(key: str) -> bytes | None:
            return await backend.get(key)

        await asyncio.gather(
            *[setter(f"k{i}", f"v{i}".encode(), 60) for i in range(20)],
            *[getter(f"k{i}") for i in range(20)],
        )
        # Все keys должны быть доступны
        for i in range(20):
            assert await backend.get(f"k{i}") == f"v{i}".encode()

    async def test_zero_ttl_immediate_expiry(self) -> None:
        """``ttl=0`` → значение expired немедленно."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=0)
        # get() видит expires_at == now → expired
        # Но между set и get проходит >0ns, поэтому expired
        assert await backend.get("k1") is None

    async def test_delete_removes_entries(self) -> None:
        """``delete`` удаляет entries (включая expired)."""
        backend = MemoryBackend(maxsize=10, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=60)
        await backend.set("k2", b"v2", ttl=60)
        await backend.delete("k1", "k2")
        assert await backend.get("k1") is None
        assert await backend.get("k2") is None

    async def test_lru_eviction_works(self) -> None:
        """maxsize=2 + 3 entries → LRU eviction первой записи."""
        backend = MemoryBackend(maxsize=2, default_ttl=3600)
        await backend.set("k1", b"v1", ttl=60)
        await backend.set("k2", b"v2", ttl=60)
        await backend.set("k3", b"v3", ttl=60)
        # k1 должна быть evicted (LRU)
        assert await backend.get("k1") is None
        assert await backend.get("k2") == b"v2"
        assert await backend.get("k3") == b"v3"
