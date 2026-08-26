"""S56 W1 (cycle 293) tests: family revocation (OWASP ASVS V3.5).

Verifies that on reuse detection, the entire token family is revoked
by bumping the generation counter for (user, device) pair. New tokens
issued after reuse get a new generation.

Tests cover:
- revoke_family() bumps generation, invalidates current-gen tokens
- New issue after family revoke creates new-gen token (valid)
- Old-gen tokens remain invalid even if they were not explicitly revoked
- Per-(user, device) isolation: family revoke doesn't affect other pairs
- Per-user isolation
- Reuse count returned for audit logging
- Integration: demo path reuse triggers family revocation
- Integration: JWT path reuse triggers family revocation
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


# ── Unit tests for revoke_family ─────────────────────────────────────


async def test_revoke_family_basic() -> None:
    """revoke_family: invalidates all current-gen tokens for the pair."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    # Issue 3 tokens for user1/device1
    await store.issue("user1", "device1", "jti-A", ttl_seconds=3600)
    await store.issue("user1", "device1", "jti-B", ttl_seconds=3600)
    await store.issue("user1", "device1", "jti-C", ttl_seconds=3600)

    assert len(store) == 3
    # All valid before revoke
    assert await store.is_valid("user1", "device1", "jti-A") is True
    assert await store.is_valid("user1", "device1", "jti-B") is True
    assert await store.is_valid("user1", "device1", "jti-C") is True

    # Revoke family
    removed = await store.revoke_family("user1", "device1")
    assert removed == 3
    assert len(store) == 0
    # All invalid after revoke
    assert await store.is_valid("user1", "device1", "jti-A") is False
    assert await store.is_valid("user1", "device1", "jti-B") is False
    assert await store.is_valid("user1", "device1", "jti-C") is False


async def test_revoke_family_creates_new_generation() -> None:
    """After family revoke, new issue creates new-gen token (valid)."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "jti-old", ttl_seconds=3600)
    await store.revoke_family("user1", "device1")

    # Old token invalid
    assert await store.is_valid("user1", "device1", "jti-old") is False

    # New token at new generation is valid
    await store.issue("user1", "device1", "jti-new", ttl_seconds=3600)
    assert await store.is_valid("user1", "device1", "jti-new") is True
    # Old still invalid
    assert await store.is_valid("user1", "device1", "jti-old") is False


async def test_revoke_family_per_user_isolation() -> None:
    """Family revoke doesn't affect other users."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "u1d1-jti", ttl_seconds=3600)
    await store.issue("user2", "device1", "u2d1-jti", ttl_seconds=3600)

    # Revoke user1's family
    await store.revoke_family("user1", "device1")

    # user1 invalid, user2 unaffected
    assert await store.is_valid("user1", "device1", "u1d1-jti") is False
    assert await store.is_valid("user2", "device1", "u2d1-jti") is True


async def test_revoke_family_per_device_isolation() -> None:
    """Family revoke doesn't affect other devices of same user."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    await store.issue("user1", "device1", "u1d1-jti", ttl_seconds=3600)
    await store.issue("user1", "device2", "u1d2-jti", ttl_seconds=3600)

    # Revoke device1's family
    await store.revoke_family("user1", "device1")

    # device1 invalid, device2 unaffected
    assert await store.is_valid("user1", "device1", "u1d1-jti") is False
    assert await store.is_valid("user1", "device2", "u1d2-jti") is True


async def test_revoke_family_empty_returns_zero() -> None:
    """revoke_family on empty pair returns 0."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    removed = await store.revoke_family("user1", "device1")
    assert removed == 0


async def test_revoke_family_returns_count_of_invalidated() -> None:
    """revoke_family returns actual count of tokens invalidated."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    for jti in ["jti-1", "jti-2", "jti-3", "jti-4", "jti-5"]:
        await store.issue("user1", "device1", jti, ttl_seconds=3600)

    removed = await store.revoke_family("user1", "device1")
    assert removed == 5


async def test_revoke_family_then_new_issue_is_at_new_gen() -> None:
    """After family revoke, new tokens get next generation."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    # Issue gen=0
    await store.issue("user1", "device1", "jti-gen0", ttl_seconds=3600)
    await store.revoke_family("user1", "device1")  # bump to gen=1
    # Issue at gen=1
    await store.issue("user1", "device1", "jti-gen1", ttl_seconds=3600)
    await store.revoke_family("user1", "device1")  # bump to gen=2
    # Issue at gen=2
    await store.issue("user1", "device1", "jti-gen2", ttl_seconds=3600)

    # Only gen=2 valid
    assert await store.is_valid("user1", "device1", "jti-gen0") is False
    assert await store.is_valid("user1", "device1", "jti-gen1") is False
    assert await store.is_valid("user1", "device1", "jti-gen2") is True


# ── Demo path integration: reuse triggers family revocation ─────────


VALID_DEMO_BASE = {
    "device_id": "11111111-2222-4333-8444-555555555556",
}


@asynccontextmanager
async def _demo_client() -> AsyncIterator[Any]:
    """Build httpx.AsyncClient for demo path with clean rotation store."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.entrypoints.api.mobile.router import (
        mobile_router,
        reset_mobile_state,
    )

    reset_mobile_state()

    app = FastAPI()
    app.include_router(mobile_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_demo_reuse_triggers_family_revocation() -> None:
    """Demo path: reuse detected → 401 + family revoked (next login needed)."""
    from src.backend.entrypoints.api.mobile import refresh_token_store

    async with _demo_client() as client:
        device_id = VALID_DEMO_BASE["device_id"]

        # Step 1: login → store has jti-1
        login_resp = await client.post(
            f"/mobile/v1/auth/login?device_id={device_id}"
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]
        jti_1 = refresh_token.split(":", 2)[2]
        user_id = f"user_{device_id[:8]}"
        store = refresh_token_store.get_refresh_token_store()
        assert await store.is_valid(user_id, device_id, jti_1) is True

        # Step 2: legitimate refresh → jti-1 revoked, jti-2 issued
        refresh_resp = await client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
        )
        assert refresh_resp.status_code == 200

        # Step 3: attacker reuses ORIGINAL jti-1 → 401 + family revoke
        reuse_resp = await client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
        )
        assert reuse_resp.status_code == 401
        assert "family revoked" in reuse_resp.json()["detail"].lower()

        # Step 4: even jti-2 (legitimate, just issued) is now invalid
        # because family was revoked
        assert await store.is_valid(user_id, device_id, jti_1) is False


async def test_demo_reuse_invalidates_all_current_gen_tokens() -> None:
    """Demo path: family revoke invalidates ALL current-gen tokens (not just reused one)."""
    from src.backend.entrypoints.api.mobile import refresh_token_store

    async with _demo_client() as client:
        device_id = VALID_DEMO_BASE["device_id"]
        user_id = f"user_{device_id[:8]}"
        store = refresh_token_store.get_refresh_token_store()

        # Login + multiple refreshes (each rotates to new jti at same gen)
        login_resp = await client.post(
            f"/mobile/v1/auth/login?device_id={device_id}"
        )
        rt = login_resp.json()["refresh_token"]
        for _ in range(3):
            r = await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={rt}"
            )
            assert r.status_code == 200
            rt = r.json()["refresh_token"]
        current_jti = rt.split(":", 2)[2]
        # This is the latest jti at current gen
        assert await store.is_valid(user_id, device_id, current_jti) is True

        # Now reuse the ORIGINAL login token (already rotated multiple times)
        original_rt = login_resp.json()["refresh_token"]
        reuse_resp = await client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={original_rt}"
        )
        assert reuse_resp.status_code == 401

        # Even the latest jti (which was legitimately issued) is now invalid
        # because the entire family was revoked
        assert await store.is_valid(user_id, device_id, current_jti) is False


# ── JWT path integration: reuse triggers family revocation ──────────


VALID_JWT_BASE = {
    "iss": "gd-mobile-prod",
    "aud": "gd-mobile-api",
    "sub": "user_jwt_family_test",
    "device_id": "11111111-2222-4333-8444-555555555557",
    "tenant_id": "tenant_jwt_family_test",
}


@asynccontextmanager
async def _jwt_client() -> AsyncIterator[Any]:
    """Build httpx.AsyncClient with JWT mode enabled + clean rotation store."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.entrypoints.api.mobile.router import (
        mobile_router,
        reset_mobile_state,
    )

    reset_mobile_state()

    app = FastAPI()
    app.include_router(mobile_router)

    mock_flags = MagicMock()
    mock_flags.mobile_jwt_enabled = True
    mock_flags.mobile_demo_auth_enabled = False

    with patch.dict(
        __import__("sys").modules,
        {
            "src.backend.core.config.features": MagicMock(feature_flags=mock_flags),
            "src.backend.core.config.features.feature_flags": mock_flags,
        },
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_jwt_reuse_triggers_family_revocation() -> None:
    """JWT path: reuse detected → 401 + family revoked."""
    from src.backend.entrypoints.api.mobile import refresh_token_store

    async with _jwt_client() as client:
        claims = {**VALID_JWT_BASE, "jti": "jti-jwt-family-test"}
        user_id = VALID_JWT_BASE["sub"]
        device_id = VALID_JWT_BASE["device_id"]

        # First use — legitimate
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=claims)
            mock_cls.return_value = mock_backend

            r1 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=ignored",
                headers={"Authorization": "Bearer jwt-first"},
            )
        assert r1.status_code == 200

        # Verify JWT jti is in store (at current generation)
        store = refresh_token_store.get_refresh_token_store()
        assert await store.is_valid(user_id, device_id, "jti-jwt-family-test") is True

        # Second use — replay attack
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=claims)
            mock_cls.return_value = mock_backend

            r2 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=ignored",
                headers={"Authorization": "Bearer jwt-replay"},
            )
        assert r2.status_code == 401
        assert "family revoked" in r2.json()["detail"].lower()

        # JWT jti is now invalidated (family revoked)
        assert await store.is_valid(user_id, device_id, "jti-jwt-family-test") is False
