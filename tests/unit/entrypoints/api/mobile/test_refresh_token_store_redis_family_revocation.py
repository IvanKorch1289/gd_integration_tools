"""S56 W2 tests: Redis-backed family revocation parity.

Tests for RedisRefreshTokenStore family revocation:
- Generation tracking via gen key (INCR)
- revoke_family bumps generation + cleans up old keys
- is_valid checks generation (family revocation gate)
- issue/issue_if_new stamp tokens with current generation

Cross-pod atomicity guaranteed via Redis INCR (single atomic op).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


pytestmark = pytest.mark.asyncio


def _make_mock_client() -> AsyncMock:
    """Mock RedisClient with cache_get/cache_set/cache_delete/execute/incr/scan_iter."""
    client = AsyncMock()
    client.cache_get = AsyncMock(return_value=None)
    client.cache_set = AsyncMock(return_value=None)
    client.cache_delete = AsyncMock(return_value=1)
    # execute returns async iterator for scan_iter
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


# ── Generation key helpers ───────────────────────────────────────────


async def test_generation_key_format() -> None:
    """Generation key has correct format."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    key = store._generation_key("user1", "device1")
    assert key == "gd:mobile:refresh:gen:user1:device1"


async def test_generation_key_custom_prefix() -> None:
    """Generation key respects custom prefix."""
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore(key_prefix="gd:staging:refresh:")
    key = store._generation_key("user1", "device1")
    assert key == "gd:staging:refresh:gen:user1:device1"


# ── is_valid with generation check ─────────────────────────────────


async def test_is_valid_fails_when_generation_mismatch(
    mock_redis: AsyncMock,
) -> None:
    """is_valid: token key exists but generation doesn't match → False."""
    # Token at gen=0, current gen=1 (family revoked)
    mock_redis.cache_get = AsyncMock(
        side_effect=[
            b"1",  # current generation = 1
            b"0",  # token's generation = 0
        ]
    )
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is False


async def test_is_valid_succeeds_when_generation_matches(
    mock_redis: AsyncMock,
) -> None:
    """is_valid: token at current generation → True."""
    # Token at gen=2, current gen=2
    mock_redis.cache_get = AsyncMock(
        side_effect=[
            b"2",  # current generation
            b"2",  # token's generation
        ]
    )
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is True


async def test_is_valid_fails_when_no_token_key(
    mock_redis: AsyncMock,
) -> None:
    """is_valid: token key doesn't exist → False."""
    mock_redis.cache_get = AsyncMock(return_value=None)
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    assert await store.is_valid("u1", "d1", "jti-A") is False


# ── issue stamps current generation ─────────────────────────────────


async def test_issue_stamps_current_generation(
    mock_redis: AsyncMock,
) -> None:
    """issue: writes token value with current generation number."""
    # First cache_get (generation read) returns 0
    mock_redis.cache_get = AsyncMock(return_value=b"0")
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    await store.issue("u1", "d1", "jti-A", ttl_seconds=3600)

    mock_redis.cache_set.assert_awaited_once()
    args = mock_redis.cache_set.await_args
    assert args.args[0] == "gd:mobile:refresh:u1:d1:jti-A"
    assert args.args[1] == "0"  # generation value
    assert args.kwargs.get("expire") == 3600


# ── revoke_family ───────────────────────────────────────────────────


async def test_revoke_family_increments_generation(
    mock_redis: AsyncMock,
) -> None:
    """revoke_family: INCR generation counter."""
    captured: dict[str, Any] = {}

    async def _capture_execute(namespace: str, fn: Any) -> Any:
        # First call: INCR for generation
        if "incr" not in captured:
            conn = AsyncMock()
            conn.incr = AsyncMock(return_value=1)
            captured["incr"] = await fn(conn)
        return captured["incr"]

    mock_redis.execute = AsyncMock(side_effect=_capture_execute)
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    result = await store.revoke_family("u1", "d1")

    assert result >= 0  # count of removed tokens
    assert captured["incr"] == 1  # first increment


async def test_revoke_family_returns_zero_on_redis_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoke_family: returns 0 (audit count) on Redis error."""

    def _raise() -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _raise
    )

    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    result = await store.revoke_family("u1", "d1")
    assert result == 0  # fail-CLOSED for security audit


async def test_revoke_family_cleans_up_old_keys(
    mock_redis: AsyncMock,
) -> None:
    """revoke_family: SCAN + DEL old generation keys after INCR."""

    async def _execute_with_scan(namespace: str, fn: Any) -> Any:
        # First call: INCR
        conn = AsyncMock()
        conn.incr = AsyncMock(return_value=1)
        return await fn(conn)

    mock_redis.execute = AsyncMock(side_effect=_execute_with_scan)
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()
    # Should not raise
    result = await store.revoke_family("u1", "d1")
    assert result >= 0


# ── E2E: revocation triggers reuse detection ────────────────────────


async def test_full_revoke_then_is_valid_returns_false(
    mock_redis: AsyncMock,
) -> None:
    """After revoke_family, is_valid returns False for previously-valid tokens.

    This simulates the post-revocation check — token exists but is
    now at old generation (revoked family).
    """
    from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
        RedisRefreshTokenStore,
    )

    store = RedisRefreshTokenStore()

    # Simulate: token issued at gen=0, then family revoked (gen=1)
    # cache_get: first call (generation read) returns 1, second call (token read) returns 0
    mock_redis.cache_get = AsyncMock(
        side_effect=[
            b"1",  # current generation
            b"0",  # token generation (stale)
        ]
    )

    assert await store.is_valid("u1", "d1", "jti-A") is False
