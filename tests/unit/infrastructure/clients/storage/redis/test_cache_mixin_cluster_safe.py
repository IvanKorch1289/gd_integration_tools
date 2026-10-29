"""Wave 18 (ADR-0391): cluster-safe UNLINK в ``CacheMixin``.

Регрессия (дефект 2, high): ``cache_delete()`` и ``cache_delete_pattern()``
вызывали ``conn.unlink(*keys)`` — multi-key UNLINK. В RedisCluster это
бросает ``CROSSSLOT`` (ключи попадают в разные hash-слоты). Волна 13
починила только ``RedisBackend.delete`` — mixin остался непочиненным.

Контракт: UNLINK вызывается ТОЛЬКО с одним ключом за вызов.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.clients.storage.redis import cache_mixin as cm_mod


class _StubConn:
    """Минимальный raw redis-клиент: фиксирует вызовы UNLINK."""

    def __init__(self, keys: list[bytes] | None = None) -> None:
        self.unlink_calls: list[tuple[bytes, ...]] = []
        self._keys = list(keys or [])

    async def unlink(self, *keys: Any) -> int:
        """UNLINK-заглушка: запоминает аргументы, считает удалённые ключи."""
        self.unlink_calls.append(keys)
        deleted = 0
        for key in keys:
            if key in self._keys:
                self._keys.remove(key)
            deleted += 1
        return deleted

    async def scan_iter(self, match: str | None = None, count: int | None = None):  # noqa: ARG002
        """SCAN-заглушка: отдаёт заранее заданные ключи."""
        for key in list(self._keys):
            yield key


class _StubCache(cm_mod.CacheMixin):
    """CacheMixin с подменённым ``execute`` — реальный op вызывается."""

    def __init__(self, conn: _StubConn) -> None:
        self._conn = conn

    async def execute(self, kind: str, operation: Any) -> Any:  # noqa: ARG002
        """Вызывает операцию на stub-соединении."""
        return await operation(self._conn)


@pytest.mark.asyncio
async def test_cache_delete_uses_single_key_unlink() -> None:
    """cache_delete(*keys) → UNLINK по одному ключу (без CROSSSLOT)."""
    conn = _StubConn()
    stub = _StubCache(conn)

    deleted = await stub.cache_delete("a", "b", "c")

    assert deleted == 3
    assert conn.unlink_calls == [("a",), ("b",), ("c",)]


@pytest.mark.asyncio
async def test_cache_delete_single_key() -> None:
    """Один ключ → один UNLINK."""
    conn = _StubConn()
    stub = _StubCache(conn)

    assert await stub.cache_delete("only") == 1
    assert conn.unlink_calls == [("only",)]


@pytest.mark.asyncio
async def test_cache_delete_empty_no_op() -> None:
    """Пустой набор ключей → UNLINK не вызывается."""
    conn = _StubConn()
    stub = _StubCache(conn)

    assert await stub.cache_delete() == 0
    assert conn.unlink_calls == []


@pytest.mark.asyncio
async def test_cache_delete_pattern_uses_single_key_unlink() -> None:
    """cache_delete_pattern → UNLINK по одному ключу (SCAN-батч не сливается)."""
    conn = _StubConn(keys=[b"k1", b"k2", b"k3"])
    stub = _StubCache(conn)

    deleted = await stub.cache_delete_pattern("k*")

    assert deleted == 3
    assert len(conn.unlink_calls) == 3
    assert all(len(call) == 1 for call in conn.unlink_calls)


@pytest.mark.asyncio
async def test_cache_delete_pattern_never_multi_key_unlink() -> None:
    """Строгая проверка: multi-key UNLINK не используется нигде в mixin."""
    conn = _StubConn(keys=[f"k{i}".encode() for i in range(50)])
    stub = _StubCache(conn)

    await stub.cache_delete_pattern("k*")

    assert conn.unlink_calls
    assert all(len(call) == 1 for call in conn.unlink_calls)
