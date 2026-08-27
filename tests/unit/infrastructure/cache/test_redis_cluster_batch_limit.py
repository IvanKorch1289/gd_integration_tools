"""P2 regression test (Cycle 9, production-grade plan).

``RedisClusterAdapter.mget_batch`` / ``mset_batch`` должны enforce
``_MAX_MGET_BATCH`` (5000) лимит на размер батча.

Pre-fix: ``mget_batch`` принимал ``keys`` любого размера → потенциальный
OOM в fan-out fallback (``asyncio.gather(*(self._cluster.get(k) for k in keys))``
создаёт N tasks одновременно для каждого key).

Post-fix: ``len(keys) > _MAX_MGET_BATCH`` → ``ValueError``.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/infrastructure/cache/test_redis_cluster_batch_limit.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.cache.redis_cluster import (
    _MAX_MGET_BATCH,
    RedisClusterAdapter,
)


class TestRedisClusterBatchLimits:
    """P2 (cycle 9): batch size guards в mget_batch / mset_batch."""

    @pytest.fixture
    def adapter(self) -> RedisClusterAdapter:
        """Mock adapter с stub RedisCluster (bypass __init__ для теста batch logic)."""
        cluster = MagicMock()
        cluster.mget = AsyncMock(return_value=[None] * 3)
        cluster.mset = AsyncMock(return_value=True)
        cluster.get = AsyncMock(return_value=None)
        cluster.set = AsyncMock(return_value=True)
        # bypass __init__ (требует startup_nodes)
        adapter = RedisClusterAdapter.__new__(RedisClusterAdapter)
        adapter._cluster = cluster
        return adapter

    @pytest.mark.asyncio
    async def test_mget_batch_under_limit_ok(self, adapter: RedisClusterAdapter) -> None:
        """3 keys → OK."""
        keys = [f"key:{i}" for i in range(3)]
        await adapter.mget_batch(keys)
        # Не вызывает ValueError

    @pytest.mark.asyncio
    async def test_mget_batch_at_limit_ok(self, adapter: RedisClusterAdapter) -> None:
        """Exactly ``_MAX_MGET_BATCH`` keys → OK."""
        # Подменим mock чтобы не создавать 5000 объектов
        adapter._cluster.mget = AsyncMock(return_value=[None] * _MAX_MGET_BATCH)
        keys = [f"key:{i}" for i in range(_MAX_MGET_BATCH)]
        await adapter.mget_batch(keys)
        # Не вызывает ValueError

    @pytest.mark.asyncio
    async def test_mget_batch_over_limit_raises(self, adapter: RedisClusterAdapter) -> None:
        """``_MAX_MGET_BATCH + 1`` keys → ``ValueError``."""
        # Не создаём реальный список (lazy gen)
        keys = (f"key:{i}" for i in range(_MAX_MGET_BATCH + 1))
        with pytest.raises(ValueError, match="oversized mget_batch"):
            await adapter.mget_batch(list(keys))

    @pytest.mark.asyncio
    async def test_mget_batch_empty_ok(self, adapter: RedisClusterAdapter) -> None:
        """Пустой список → OK (early return)."""
        result = await adapter.mget_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_mset_batch_under_limit_ok(self, adapter: RedisClusterAdapter) -> None:
        """3 items → OK."""
        mapping = {f"key:{i}": f"value:{i}" for i in range(3)}
        await adapter.mset_batch(mapping)

    @pytest.mark.asyncio
    async def test_mset_batch_over_limit_raises(self, adapter: RedisClusterAdapter) -> None:
        """``_MAX_MGET_BATCH + 1`` items → ``ValueError``."""
        mapping = {f"key:{i}": f"value:{i}" for i in range(_MAX_MGET_BATCH + 1)}
        with pytest.raises(ValueError, match="oversized mset_batch"):
            await adapter.mset_batch(mapping)

    @pytest.mark.asyncio
    async def test_mset_batch_empty_ok(self, adapter: RedisClusterAdapter) -> None:
        """Пустой dict → OK (early return)."""
        await adapter.mset_batch({})

    def test_max_batch_constant_is_5000(self) -> None:
        """``_MAX_MGET_BATCH = 5000`` (parity с cache_mixin.py:1000 * 5 для cluster)."""
        assert _MAX_MGET_BATCH == 5000
