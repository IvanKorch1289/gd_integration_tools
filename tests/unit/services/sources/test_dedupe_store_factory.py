"""Unit tests for ``make_dedupe_store`` (S64 W4).

Проверяют:
* default (flag=False) → MemoryDedupeStore;
* flag=True → RedisDedupeStore с Redis-клиентом ``"cache"`` kind;
* исключения из ``get_redis_client()`` НЕ глотаются (fail-fast).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.sources.idempotency import MemoryDedupeStore, RedisDedupeStore
from src.backend.services.sources.lifecycle import make_dedupe_store


@pytest.mark.asyncio
async def test_make_dedupe_store_default_returns_memory() -> None:
    """``use_redis_dedupe=False`` (default) → MemoryDedupeStore."""
    fake_settings = MagicMock()
    fake_settings.use_redis_dedupe = False
    with patch(
        "src.backend.core.config.services.outbox.outbox_settings", new=fake_settings
    ):
        store = await make_dedupe_store()
    assert isinstance(store, MemoryDedupeStore)


@pytest.mark.asyncio
async def test_make_dedupe_store_redis_returns_redis_store() -> None:
    """``use_redis_dedupe=True`` → RedisDedupeStore с клиентом kind='cache'."""
    fake_settings = MagicMock()
    fake_settings.use_redis_dedupe = True
    fake_redis_instance = MagicMock(name="redis.cache")
    fake_redis_client_singleton = MagicMock()
    fake_redis_client_singleton.get_client = AsyncMock(return_value=fake_redis_instance)
    with (
        patch(
            "src.backend.core.config.services.outbox.outbox_settings", new=fake_settings
        ),
        patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            return_value=fake_redis_client_singleton,
        ),
    ):
        store = await make_dedupe_store()
    assert isinstance(store, RedisDedupeStore)
    # RedisDedupeStore.__init__ принимает redis instance
    assert store._redis is fake_redis_instance  # noqa: SLF001
    # kind="cache" использован для RedisClient.get_client
    fake_redis_client_singleton.get_client.assert_awaited_once_with("cache")


@pytest.mark.asyncio
async def test_make_dedupe_store_propagates_redis_get_client_error() -> None:
    """Ошибка ``get_client`` НЕ глотается — пусть startup решает.

    Redis недоступен → fail-fast. ``RedisDedupeStore`` сам degrade'ит
    только на ``set()`` (см. ``idempotency.py:RedisDedupeStore.is_duplicate``).
    """
    fake_settings = MagicMock()
    fake_settings.use_redis_dedupe = True
    fake_redis_client_singleton = MagicMock()
    fake_redis_client_singleton.get_client = AsyncMock(
        side_effect=ConnectionError("redis down")
    )
    with (
        patch(
            "src.backend.core.config.services.outbox.outbox_settings", new=fake_settings
        ),
        patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            return_value=fake_redis_client_singleton,
        ),
    ):
        with pytest.raises(ConnectionError, match="redis down"):
            await make_dedupe_store()
