"""S54 W2 (cycle 290) tests: refresh endpoint rotation integration.

Verifies that the /auth/login and /auth/refresh endpoints are wired
to the InMemoryRefreshTokenStore for rotation tracking:

1. /auth/login issues + tracks new refresh token via store.issue()
2. /auth/refresh rotates via store.revoke() + store.issue()
3. Reuse of already-rotated token -> 401 (attack detection)
4. reset_mobile_state() also clears the rotation store

Uses async TestClient (httpx.AsyncClient + ASGITransport) so tests can
await both the endpoint responses and the rotation store methods
within a single event loop.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


async def _build_client() -> Any:
    """Build a fresh httpx.AsyncClient for mobile_router."""
    from httpx import ASGITransport, AsyncClient

    from src.backend.entrypoints.api.mobile.router import (
        mobile_router,
        reset_mobile_state,
    )

    # Hygiene: clear all in-memory state including rotation store
    # before each test for isolation.
    reset_mobile_state()

    app = __import__("fastapi", fromlist=["FastAPI"]).FastAPI()
    app.include_router(mobile_router)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_login_tracks_refresh_token_in_store() -> None:
    """After /auth/login, the issued refresh token jti is in the rotation store.

    This is the foundation of reuse detection — without store tracking,
    /auth/refresh would accept ANY well-formatted refresh token.
    """
    from src.backend.entrypoints.api.mobile import refresh_token_store

    client = await _build_client()
    device_id = "aaaaaaaa-1111-4222-8333-444444444444"

    login_resp = await client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]
    jti = refresh_token.split(":", 2)[2]
    user_id = f"user_{device_id[:8]}"

    store = refresh_token_store.get_refresh_token_store()
    assert await store.is_valid(user_id, device_id, jti) is True


async def test_refresh_rotates_via_store() -> None:
    """/auth/refresh rotates: old jti revoked, new jti issued in store."""
    from src.backend.entrypoints.api.mobile import refresh_token_store

    client = await _build_client()
    device_id = "bbbbbbbb-2222-4333-8444-555555555555"

    login_resp = await client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    old_refresh = login_resp.json()["refresh_token"]
    old_jti = old_refresh.split(":", 2)[2]
    user_id = f"user_{device_id[:8]}"

    refresh_resp = await client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={old_refresh}"
    )
    assert refresh_resp.status_code == 200
    new_refresh = refresh_resp.json()["refresh_token"]
    new_jti = new_refresh.split(":", 2)[2]
    assert old_jti != new_jti

    # Old should be revoked, new should be valid
    store = refresh_token_store.get_refresh_token_store()
    assert await store.is_valid(user_id, device_id, old_jti) is False
    assert await store.is_valid(user_id, device_id, new_jti) is True


async def test_reuse_of_rotated_token_returns_401() -> None:
    """Reuse attack: presenting an already-rotated token -> 401.

    This is the core security guarantee of rotation — attacker who
    captured old token cannot use it after legitimate refresh.
    """
    client = await _build_client()
    device_id = "cccccccc-3333-4444-8555-666666666666"

    login_resp = await client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    refresh_token = login_resp.json()["refresh_token"]

    # Legitimate refresh (rotates the token)
    refresh_resp = await client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
    )
    assert refresh_resp.status_code == 200

    # Attacker tries to reuse the OLD token
    reuse_resp = await client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
    )
    assert reuse_resp.status_code == 401
    assert "invalid" in reuse_resp.json()["detail"].lower()


async def test_unissued_token_rejected() -> None:
    """A well-formed refresh token NOT issued by login -> 401.

    Prevents forged tokens from being accepted just because they
    match the format.
    """
    client = await _build_client()
    device_id = "dddddddd-4444-4555-8666-777777777777"
    # Format matches but never went through login -> store has no record
    fake_refresh = "mobile-refresh:user_dddddddd:deadbeefcafebabe"

    resp = await client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={fake_refresh}"
    )
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"].lower()


async def test_reset_mobile_state_clears_rotation_store() -> None:
    """reset_mobile_state() clears refresh token store for test isolation."""
    from src.backend.entrypoints.api.mobile import refresh_token_store
    from src.backend.entrypoints.api.mobile.router import reset_mobile_state

    # Issue a token
    store = refresh_token_store.get_refresh_token_store()
    await store.issue("user_x", "device_x", "test-jti", ttl_seconds=3600)
    assert await store.is_valid("user_x", "device_x", "test-jti") is True

    # Reset
    reset_mobile_state()

    # Singleton is reset; first access creates new empty store
    fresh_store = refresh_token_store.get_refresh_token_store()
    # Old tokens are gone (new store instance).
    assert await fresh_store.is_valid("user_x", "device_x", "test-jti") is False
