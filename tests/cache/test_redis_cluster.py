"""Smoke-тесты для :class:`RedisClusterAdapter` (Sprint 3 К2 W1).

Тесты не требуют живого Redis cluster — проверяют:

* конструктор корректно строит ``redis.asyncio.cluster.RedisCluster``;
* :meth:`ping` обрабатывает dict-результат и normalize-ит к ``bool``;
* :meth:`close` идемпотентна (повторный вызов не падает).

Реальный cluster в integration-тестах: requires testcontainers Redis
cluster image, pytest.skip если недоступен — здесь не используется.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# redis 5.x обязателен; skip — если случайно отсутствует.
redis_mod = pytest.importorskip("redis.asyncio.cluster")

from src.backend.infrastructure.cache.redis_cluster import RedisClusterAdapter


def _make_adapter_with_mock_cluster() -> tuple[RedisClusterAdapter, MagicMock]:
    """Создаёт adapter с замоканным RedisCluster (без сетевых попыток).

    Returns:
        tuple ``(adapter, mock_cluster_instance)``.
    """
    from redis.asyncio.cluster import ClusterNode

    mock_cluster_instance = MagicMock()
    mock_cluster_instance.ping = AsyncMock(return_value=True)
    mock_cluster_instance.aclose = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.cluster.RedisCluster", return_value=mock_cluster_instance
    ):
        adapter = RedisClusterAdapter(
            startup_nodes=[ClusterNode(host="redis-1", port=6379)],
            max_connections=50,
            socket_keepalive=True,
            health_check_interval=30,
        )
    return adapter, mock_cluster_instance


@pytest.mark.asyncio
async def test_adapter_ping_returns_true_on_success() -> None:
    """ping() с положительным ответом от cluster → True."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    mock_cluster.ping.return_value = True
    assert await adapter.ping() is True
    mock_cluster.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_ping_returns_true_on_dict_all_success() -> None:
    """Если cluster.ping возвращает dict — нормализуется к True."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    mock_cluster.ping.return_value = {"node1": True, "node2": True}
    assert await adapter.ping() is True


@pytest.mark.asyncio
async def test_adapter_ping_returns_false_on_dict_any_failure() -> None:
    """Если хотя бы один узел не отвечает — ping() возвращает False."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    mock_cluster.ping.return_value = {"node1": True, "node2": False}
    assert await adapter.ping() is False


@pytest.mark.asyncio
async def test_adapter_ping_returns_false_on_exception() -> None:
    """Любое исключение в ping() → False (логирование WARNING)."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    mock_cluster.ping.side_effect = ConnectionError("cluster unreachable")
    assert await adapter.ping() is False


@pytest.mark.asyncio
async def test_adapter_close_is_idempotent() -> None:
    """Повторный close() — no-op, не падает."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    await adapter.close()
    await adapter.close()  # повторный — не должен снова вызывать aclose
    assert mock_cluster.aclose.await_count == 1


@pytest.mark.asyncio
async def test_adapter_close_fallback_to_close_on_attribute_error() -> None:
    """Если aclose отсутствует (redis-py <5) — fallback к close()."""
    from redis.asyncio.cluster import ClusterNode

    mock_cluster_instance = MagicMock()
    # имитируем redis-py <5: aclose отсутствует
    mock_cluster_instance.aclose = AsyncMock(side_effect=AttributeError("no aclose"))
    mock_cluster_instance.close = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.cluster.RedisCluster", return_value=mock_cluster_instance
    ):
        adapter = RedisClusterAdapter(
            startup_nodes=[ClusterNode(host="redis-1", port=6379)]
        )
        await adapter.close()

    mock_cluster_instance.close.assert_awaited_once()


def test_adapter_client_property_returns_underlying_cluster() -> None:
    """``adapter.client`` — прозрачный доступ к нижележащему RedisCluster."""
    adapter, mock_cluster = _make_adapter_with_mock_cluster()
    assert adapter.client is mock_cluster
