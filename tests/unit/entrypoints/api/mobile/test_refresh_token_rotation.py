"""S52 W3 tests: refresh token rotation store.

Per ADR-0267 (S52 plan): mobile JWT refresh endpoint should rotate
refresh tokens via this store. Tests verify rotation tracking.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_new_token_is_valid() -> None:
    """Issued refresh token is valid (is_valid returns True)."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "jti-abc", ttl_seconds=3600)

    assert await store.is_valid("user1", "device1", "jti-abc") is True


async def test_unissued_token_is_invalid() -> None:
    """Unissued refresh token is invalid."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    assert await store.is_valid("user1", "device1", "never-issued") is False


async def test_revoked_token_is_invalid() -> None:
    """Revoked refresh token becomes invalid."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "jti-abc", ttl_seconds=3600)
    assert await store.is_valid("user1", "device1", "jti-abc") is True

    await store.revoke("user1", "device1", "jti-abc")
    assert await store.is_valid("user1", "device1", "jti-abc") is False


async def test_rotation_replaces_old_token() -> None:
    """Rotation flow: issue → revoke old → issue new.

    Simulates refresh endpoint rotation:
    1. Issue initial refresh token
    2. User requests refresh → revoke old, issue new
    3. Old token should be invalid (prevents reuse attack)
    4. New token should be valid
    """
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()

    # Initial login
    await store.issue("user1", "device1", "old-jti", ttl_seconds=3600)

    # Refresh endpoint rotates
    await store.revoke("user1", "device1", "old-jti")
    await store.issue("user1", "device1", "new-jti", ttl_seconds=3600)

    # Verify state
    assert await store.is_valid("user1", "device1", "old-jti") is False
    assert await store.is_valid("user1", "device1", "new-jti") is True


async def test_per_user_isolation() -> None:
    """Different users have independent refresh token stores."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "jti-user1", ttl_seconds=3600)

    # Different user — should be invalid
    assert await store.is_valid("user2", "device1", "jti-user1") is False
    # Same user — should be valid
    assert await store.is_valid("user1", "device1", "jti-user1") is True


async def test_per_device_isolation() -> None:
    """Different devices have independent refresh token stores."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "jti-1", ttl_seconds=3600)

    # Different device — should be invalid
    assert await store.is_valid("user1", "device2", "jti-1") is False
    # Same device — should be valid
    assert await store.is_valid("user1", "device1", "jti-1") is True


async def test_token_expiry() -> None:
    """Expired refresh token is invalid (auto-cleanup)."""
    import asyncio

    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    # Use ttl_seconds=1 (minimum allowed) and wait > 1 sec
    await store.issue("user1", "device1", "jti-short", ttl_seconds=1)
    assert await store.is_valid("user1", "device1", "jti-short") is True

    await asyncio.sleep(1.1)
    # Expired — auto-cleanup
    assert await store.is_valid("user1", "device1", "jti-short") is False


async def test_issue_rejects_invalid_args() -> None:
    """issue() validates arguments."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    with pytest.raises(ValueError, match="refresh_jti"):
        await store.issue("u", "d", "", ttl_seconds=3600)

    with pytest.raises(ValueError, match="ttl_seconds"):
        await store.issue("u", "d", "jti", ttl_seconds=-1)


async def test_rotation_reuse_detection() -> None:
    """Reuse attack detection: if old token used after rotation, raise alert.

    In a full implementation, this would trigger family revocation.
    Here we just verify the OLD token becomes invalid after rotation.
    """
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()

    # Step 1: user logs in
    await store.issue("user1", "device1", "initial-jti", ttl_seconds=3600)

    # Step 2: legitimate user refreshes (rotation)
    await store.revoke("user1", "device1", "initial-jti")
    await store.issue("user1", "device1", "rotated-jti", ttl_seconds=3600)

    # Step 3: attacker tries to use the OLD token
    # (in production, this would trigger family revocation alert)
    assert await store.is_valid("user1", "device1", "initial-jti") is False
    # New token still works
    assert await store.is_valid("user1", "device1", "rotated-jti") is True


async def test_singleton_store_returns_same_instance() -> None:
    """get_refresh_token_store returns singleton."""
    from src.backend.entrypoints.api.mobile import refresh_token_store

    # Reset singleton for test
    refresh_token_store._default_store = None

    store1 = refresh_token_store.get_refresh_token_store()
    store2 = refresh_token_store.get_refresh_token_store()
    assert store1 is store2
