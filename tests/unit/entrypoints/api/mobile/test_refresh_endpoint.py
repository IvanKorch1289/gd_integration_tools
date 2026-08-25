"""Tests for mobile /auth/refresh endpoint (S48 W2, ADR-0267).

Verifies:
1. Valid refresh token + matching device_id → 200 + new tokens
2. Invalid refresh token format → 401
3. Malformed refresh token → 401
4. Device ID mismatch → 400
5. New tokens are different from old (token rotation)
6. User_id preserved through refresh
"""

from __future__ import annotations

import pytest


def _build_client() -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.backend.entrypoints.api.mobile.router import mobile_router

    app = FastAPI()
    app.include_router(mobile_router)
    return TestClient(app)


def test_refresh_with_valid_token_returns_new_pair() -> None:
    """Valid refresh + matching device_id → 200 with new tokens."""
    client = _build_client()
    device_id = "11111111-2222-4333-8444-555555555555"
    # First, login to get refresh token
    login_resp = client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    refresh_token = login_data["refresh_token"]

    # Now refresh
    refresh_resp = client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
    )
    assert refresh_resp.status_code == 200
    new_data = refresh_resp.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data
    assert new_data["expires_in"] == 900


def test_refresh_returns_different_tokens() -> None:
    """Refresh produces new tokens (rotation)."""
    client = _build_client()
    device_id = "22222222-3333-4444-5555-666666666666"
    login_resp = client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    old_refresh = login_resp.json()["refresh_token"]

    refresh_resp = client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={old_refresh}"
    )
    new_tokens = refresh_resp.json()
    assert new_tokens["access_token"] != login_resp.json()["access_token"]
    assert new_tokens["refresh_token"] != old_refresh


def test_refresh_preserves_user_id() -> None:
    """New tokens have same user_id (user_<device_id[:8]>) as old."""
    client = _build_client()
    device_id = "33333333-4444-4555-8666-777777777777"
    login_resp = client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    login_data = login_resp.json()

    refresh_resp = client.post(
        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={login_data['refresh_token']}"
    )
    new_access = refresh_resp.json()["access_token"]
    # Extract user_id from new access token
    assert new_access.startswith(f"mobile:user_{device_id[:8]}:")


def test_refresh_with_invalid_format_returns_401() -> None:
    """Refresh token without mobile-refresh: prefix → 401."""
    client = _build_client()
    resp = client.post(
        "/mobile/v1/auth/refresh?device_id=11111111-2222-4333-8444-555555555555&refresh_token=invalid_token"
    )
    assert resp.status_code == 401
    assert "Invalid refresh token format" in resp.json()["detail"]


def test_refresh_with_malformed_token_returns_401() -> None:
    """Refresh token with mobile-refresh: prefix but wrong parts → 401."""
    client = _build_client()
    resp = client.post(
        "/mobile/v1/auth/refresh?device_id=11111111-2222-4333-8444-555555555555&refresh_token=mobile-refresh:only_one_part"
    )
    assert resp.status_code == 401
    assert "Malformed" in resp.json()["detail"]


def test_refresh_with_device_id_mismatch_returns_400() -> None:
    """Refresh token issued for device A, presented with device B → 400."""
    client = _build_client()
    device_a = "11111111-2222-4333-8444-555555555555"
    device_b = "99999999-8888-7777-6666-555555555555"
    login_resp = client.post(f"/mobile/v1/auth/login?device_id={device_a}")
    refresh_token = login_resp.json()["refresh_token"]

    # Try to refresh with wrong device_id
    resp = client.post(
        f"/mobile/v1/auth/refresh?device_id={device_b}&refresh_token={refresh_token}"
    )
    assert resp.status_code == 400
    assert "Device ID" in resp.json()["detail"]


def test_refresh_endpoint_documented() -> None:
    """Verify refresh endpoint exists in router."""
    from src.backend.entrypoints.api.mobile.router import mobile_router

    routes = [r.path for r in mobile_router.routes if hasattr(r, "path")]
    assert any("/auth/refresh" in r for r in routes), (
        f"Refresh endpoint not found. Routes: {routes}"
    )
