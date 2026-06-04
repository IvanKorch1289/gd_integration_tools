"""Unit-тесты Redis Cluster pipelining + batch ops (S13 K2 W6).

Использует mock'и т.к. реальный 3-node testcontainer недоступен в unit-suite.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def adapter_with_mock_cluster(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Создаёт RedisClusterAdapter c mock'нутым _cluster."""
    from src.backend.infrastructure.cache.redis_cluster import RedisClusterAdapter

    # Подменяем RedisCluster import чтобы не пытаться подключиться.
    fake_cluster = MagicMock()
    fake_cluster.mget = AsyncMock(return_value=[b"v1", b"v2", None])
    fake_cluster.mset = AsyncMock()
    fake_cluster.get = AsyncMock(side_effect=[b"v1", b"v2", None])
    fake_cluster.set = AsyncMock()
    fake_cluster.scan_iter = MagicMock()
    fake_cluster.eval = AsyncMock(return_value=1)
    fake_cluster.pipeline = MagicMock(return_value=MagicMock())
    fake_cluster.ping = AsyncMock(return_value=True)
    fake_cluster.aclose = AsyncMock()

    import redis.asyncio.cluster as rcluster_mod

    monkeypatch.setattr(
        rcluster_mod, "RedisCluster", MagicMock(return_value=fake_cluster)
    )

    adapter = RedisClusterAdapter(startup_nodes=[])
    return adapter, fake_cluster


@pytest.mark.asyncio
async def test_mget_batch_uses_native_mget(adapter_with_mock_cluster: tuple) -> None:
    adapter, fake = adapter_with_mock_cluster
    result = await adapter.mget_batch(["k1", "k2", "k3"])
    fake.mget.assert_awaited_once_with(["k1", "k2", "k3"])
    assert result == [b"v1", b"v2", None]


@pytest.mark.asyncio
async def test_mget_batch_empty_returns_empty(adapter_with_mock_cluster) -> None:
    adapter, fake = adapter_with_mock_cluster
    assert await adapter.mget_batch([]) == []
    fake.mget.assert_not_awaited()


@pytest.mark.asyncio
async def test_mget_batch_fallback_on_mget_error(
    adapter_with_mock_cluster: tuple,
) -> None:
    adapter, fake = adapter_with_mock_cluster
    fake.mget = AsyncMock(side_effect=RuntimeError("slot mismatch"))
    result = await adapter.mget_batch(["k1", "k2", "k3"])
    assert result == [b"v1", b"v2", None]
    assert fake.get.await_count == 3


@pytest.mark.asyncio
async def test_mset_batch_uses_native_mset(adapter_with_mock_cluster) -> None:
    adapter, fake = adapter_with_mock_cluster
    await adapter.mset_batch({"k1": "v1", "k2": "v2"})
    fake.mset.assert_awaited_once()


@pytest.mark.asyncio
async def test_mset_batch_empty_skips(adapter_with_mock_cluster) -> None:
    adapter, fake = adapter_with_mock_cluster
    await adapter.mset_batch({})
    fake.mset.assert_not_awaited()


@pytest.mark.asyncio
async def test_eval_script_lua(adapter_with_mock_cluster) -> None:
    adapter, fake = adapter_with_mock_cluster
    fake.eval = AsyncMock(return_value=1)
    result = await adapter.eval_script(
        "return KEYS[1]", keys=["{user:42}:lock"], args=["30"]
    )
    fake.eval.assert_awaited_once()
    assert result == 1


def test_pipeline_returns_native(adapter_with_mock_cluster) -> None:
    adapter, fake = adapter_with_mock_cluster
    pipe = adapter.pipeline(routing_key="user:42")
    fake.pipeline.assert_called_once()
    assert pipe is not None
