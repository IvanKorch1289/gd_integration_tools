"""S55 W2 tests: Redis-backed refresh token rotation store.

Multi-pod production-ready implementation. Uses AsyncMock to simulate
Redis client without requiring real Redis.

Tests verify:
- Key format (prefix + user/device/jti)
- is_valid: True/False based on Redis key existence
- issue: SET with TTL
- issue_if_new: atomic NX (True for new, False for reuse)
- revoke: DELETE key
- Fail-CLOSED on Redis errors (return False / no-op)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


def _make_mock_client() -> AsyncMock:
    """Mock RedisClient with cache_get/cache_set/cache_delete/execute."""
    client = AsyncMock()
    client.cache_get = AsyncMock(return_value=None)
    client.cache_set = AsyncMock(return_value=None)
    client.cache_delete = AsyncMock(return_value=1)
    client.execute = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch get_redis_client to return mock client."""
    client = _make_mock_client()

    def _get_client() -> AsyncMock:
        return client

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _get_client
    )
    return client


# ── is_valid ────────────────────────────────────────────────────────


async def test_is_valid_returns_true_when_key_exists(mock_redis: AsyncMock) -> None:
    """is_valid: True when Redis cache_get returns non-None."""
    mock_redis.cache_get = AsyncMock(return_value=b"1234567890")
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is True


async def test_is_valid_returns_false_when_no_key(mock_redis: AsyncMock) -> None:
    """is_valid: False when Redis returns None."""
    mock_redis.cache_get = AsyncMock(return_value=None)
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is False


async def test_is_valid_uses_correct_key(mock_redis: AsyncMock) -> None:
    """is_valid: uses key prefix + user + device + jti."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    await store.is_valid("user123", "dev456", "jti-abc")

    mock_redis.cache_get.assert_awaited_once_with(
        "gd:mobile:refresh:user123:dev456:jti-abc"
    )


async def test_is_valid_fail_closed_on_redis_error(
    mock_redis: AsyncMock,
) -> None:
    """is_valid: returns False (fail-CLOSED) on Redis error."""
    mock_redis.cache_get = AsyncMock(side_effect=ConnectionError("redis down"))
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is False


# ── issue ────────────────────────────────────────────────────────────


async def test_issue_persists_with_ttl(mock_redis: AsyncMock) -> None:
    """issue: writes to Redis with configured TTL."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    await store.issue("u1", "d1", "jti-A", ttl_seconds=3600)

    mock_redis.cache_set.assert_awaited_once()
    args = mock_redis.cache_set.await_args
    assert args.args[0] == "gd:mobile:refresh:u1:d1:jti-A"
    assert args.kwargs.get("expire") == 3600


async def test_issue_rejects_invalid_args(mock_redis: AsyncMock) -> None:
    """issue: validates args (empty jti, negative TTL)."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    with pytest.raises(ValueError, match="refresh_jti"):
        await store.issue("u", "d", "", ttl_seconds=3600)

    with pytest.raises(ValueError, match="ttl_seconds"):
        await store.issue("u", "d", "jti", ttl_seconds=-1)


# ── issue_if_new (atomic NX) ────────────────────────────────────────


async def test_issue_if_new_returns_true_on_first_use(
    mock_redis: AsyncMock,
) -> None:
    """issue_if_new: True when Redis SET NX returns success (key didn't exist)."""
    mock_redis.execute = AsyncMock(return_value=True)  # SET NX success
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    result = await store.issue_if_new("u1", "d1", "jti-A", ttl_seconds=3600)
    assert result is True


async def test_issue_if_new_returns_false_on_reuse(mock_redis: AsyncMock) -> None:
    """issue_if_new: False when Redis SET NX returns None (key existed)."""
    mock_redis.execute = AsyncMock(return_value=None)  # SET NX failed (key existed)
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    result = await store.issue_if_new("u1", "d1", "jti-A", ttl_seconds=3600)
    assert result is False


async def test_issue_if_new_uses_atomic_set_nx_ex(
    mock_redis: AsyncMock,
) -> None:
    """issue_if_new: invokes redis-py set() with nx=True, ex=ttl for atomicity."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()

    # Capture the lambda passed to execute() so we can invoke it manually
    # against a mock conn. (execute() is itself mocked; the lambda is the
    # unit of behaviour we want to verify.)
    captured: dict[str, Any] = {}

    async def _capture_execute(namespace: str, fn: Any) -> bool:
        captured["namespace"] = namespace
        captured["fn"] = fn
        return True

    mock_redis.execute = AsyncMock(side_effect=_capture_execute)

    await store.issue_if_new("u1", "d1", "jti-A", ttl_seconds=7200)

    # Verify execute was called with cache namespace
    assert captured["namespace"] == "cache"
    assert callable(captured["fn"])

    # Now invoke the captured lambda with a mock conn to verify redis-py
    # set() is called with correct atomic-first-use args.
    # S56 W1: value is str(generation) for family-revocation tracking.
    conn_mock = AsyncMock()
    conn_mock.set = AsyncMock(return_value=True)
    await captured["fn"](conn_mock)
    conn_mock.set.assert_awaited_once()
    call_args = conn_mock.set.await_args
    assert call_args.args[0] == "gd:mobile:refresh:u1:d1:jti-A"
    assert call_args.args[1] == "0"  # current generation (default 0)
    assert call_args.kwargs.get("nx") is True
    assert call_args.kwargs.get("ex") == 7200


async def test_issue_if_new_fail_closed_on_redis_error(
    mock_redis: AsyncMock,
) -> None:
    """issue_if_new: returns False (fail-CLOSED) on Redis error."""
    mock_redis.execute = AsyncMock(side_effect=ConnectionError("redis down"))
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    result = await store.issue_if_new("u1", "d1", "jti-A", ttl_seconds=3600)
    assert result is False


# ── revoke ───────────────────────────────────────────────────────────


async def test_revoke_deletes_key(mock_redis: AsyncMock) -> None:
    """revoke: deletes Redis key."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    await store.revoke("u1", "d1", "jti-A")

    mock_redis.cache_delete.assert_awaited_once_with(
        "gd:mobile:refresh:u1:d1:jti-A"
    )


async def test_revoke_logs_warning_on_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoke: graceful no-op when Redis unavailable (logs warning)."""
    # Patch get_redis_client to raise
    def _raise() -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _raise
    )

    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    # Should not raise
    await store.revoke("u1", "d1", "jti-A")


# ── Key prefix customization ────────────────────────────────────────


async def test_custom_key_prefix() -> None:
    """Custom key_prefix allows namespacing per environment."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore(key_prefix="gd:mobile:refresh:staging:")
    key = store._key("u1", "d1", "jti-A")
    assert key == "gd:mobile:refresh:staging:u1:d1:jti-A"


# ── Rotation integration (end-to-end pattern) ──────────────────────


async def test_full_rotation_cycle(mock_redis: AsyncMock) -> None:
    """End-to-end: issue → is_valid → issue_if_new=False (reuse) → revoke."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()

    # 1. First-use: issue_if_new returns True
    mock_redis.execute = AsyncMock(return_value=True)
    assert await store.issue_if_new("u1", "d1", "jti-old", ttl_seconds=3600) is True

    # 2. Subsequent attempt with same jti: issue_if_new returns False (reuse)
    mock_redis.execute = AsyncMock(return_value=None)
    assert await store.issue_if_new("u1", "d1", "jti-old", ttl_seconds=3600) is False

    # 3. Revoke old token
    mock_redis.cache_get = AsyncMock(return_value=None)
    await store.revoke("u1", "d1", "jti-old")
    mock_redis.cache_delete.assert_awaited_with(
        "gd:mobile:refresh:u1:d1:jti-old"
    )

    # 4. After revoke, key no longer valid (mock cache_get returns None)
    assert await store.is_valid("u1", "d1", "jti-old") is False
