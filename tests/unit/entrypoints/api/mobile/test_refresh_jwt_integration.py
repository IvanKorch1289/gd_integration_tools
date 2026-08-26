"""Tests for mobile /auth/refresh JWT path integration (S49 W3, cycle 275).

Pattern follows test_mobile_router_jwt_integration.py (proven working).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _build_client_with_flags(
    *,
    mobile_jwt_enabled: bool = False,
    mobile_demo_auth_enabled: bool = True,
) -> Any:
    """Build TestClient with given feature flag configuration.

    S55 W1: also call ``reset_mobile_state()`` before yielding the
    client to ensure clean rotation store state. Without this, JWT
    tests using hardcoded ``VALID_JWT_CLAIMS["jti"]`` would leak
    state across tests and trigger false reuse-detection 401s.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.backend.entrypoints.api.mobile.router import (
        mobile_router,
        reset_mobile_state,
    )

    # Hygiene: clear all in-memory state including rotation store.
    reset_mobile_state()

    app = FastAPI()
    app.include_router(mobile_router)

    mock_flags = MagicMock()
    mock_flags.mobile_jwt_enabled = mobile_jwt_enabled
    mock_flags.mobile_demo_auth_enabled = mobile_demo_auth_enabled

    with patch.dict(
        "sys.modules",
        {
            "src.backend.core.config.features": MagicMock(feature_flags=mock_flags),
            "src.backend.core.config.features.feature_flags": mock_flags,
        },
    ):
        with TestClient(app) as client:
            yield client, mock_flags


VALID_JWT_CLAIMS = {
    "iss": "gd-mobile-prod",
    "aud": "gd-mobile-api",
    "sub": "user_jwt_test",
    "device_id": "11111111-2222-4333-8444-555555555555",
    "tenant_id": "tenant_jwt_test",
    "jti": "jti-refresh-test",
}


def _login_via_demo(client: Any, device_id: str) -> str:
    """Helper: get demo refresh_token via /auth/login."""
    login_resp = client.post(f"/mobile/v1/auth/login?device_id={device_id}")
    return login_resp.json()["refresh_token"]


# ── Demo mode (backward compat) ───────────────────────────────────


def test_demo_mode_refresh_works_without_auth_header() -> None:
    """Demo mode: refresh endpoint works without Authorization header."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=False, mobile_demo_auth_enabled=True
    ):
        device_id = "11111111-2222-4333-8444-555555555555"
        refresh_token = _login_via_demo(client, device_id)

        resp = client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
        )
        assert resp.status_code == 200


# ── JWT mode ──────────────────────────────────────────────────────


def test_jwt_mode_requires_authorization_header() -> None:
    """JWT mode: missing Authorization header → 401."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        device_id = VALID_JWT_CLAIMS["device_id"]
        refresh_token = f"mobile-refresh:user_{device_id[:8]}:abc123"

        resp = client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
        )
        assert resp.status_code == 401
        assert "Authorization" in resp.json()["detail"]


def test_jwt_mode_rejects_non_bearer_auth() -> None:
    """JWT mode: Authorization without Bearer prefix → 401."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        device_id = VALID_JWT_CLAIMS["device_id"]
        refresh_token = f"mobile-refresh:user_{device_id[:8]}:abc123"

        resp = client.post(
            f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401


def test_jwt_mode_with_valid_jwt_returns_new_tokens() -> None:
    """JWT mode: valid JWT → 200 + new token pair."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=VALID_JWT_CLAIMS)
            mock_cls.return_value = mock_backend

            device_id = VALID_JWT_CLAIMS["device_id"]
            refresh_token = "ignored_in_jwt_mode:abc"

            resp = client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}",
                headers={"Authorization": "Bearer valid.jwt.token"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "user_jwt_test" in data["access_token"]


def test_jwt_mode_uses_jwt_user_id_not_refresh_token() -> None:
    """JWT mode: refresh_token user_id is IGNORED, JWT user_id is used."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=VALID_JWT_CLAIMS)
            mock_cls.return_value = mock_backend

            device_id = VALID_JWT_CLAIMS["device_id"]
            refresh_token = "mobile-refresh:user_from_refresh:abc123"

            resp = client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}",
                headers={"Authorization": "Bearer valid.jwt.token"},
            )
            assert resp.status_code == 200
            assert "user_jwt_test" in resp.json()["access_token"]
            assert "user_from_refresh" not in resp.json()["access_token"]


def test_jwt_mode_device_id_mismatch_returns_400() -> None:
    """JWT mode: device_id query != JWT device_id claim → 400."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=VALID_JWT_CLAIMS)
            mock_cls.return_value = mock_backend

            wrong_device_id = "99999999-8888-7777-6666-555555555555"

            resp = client.post(
                f"/mobile/v1/auth/refresh?device_id={wrong_device_id}&refresh_token=anything",
                headers={"Authorization": "Bearer valid.jwt.token"},
            )
            assert resp.status_code == 400
            assert "Device ID" in resp.json()["detail"]


def test_jwt_mode_invalid_jwt_returns_401() -> None:
    """JWT mode: JwtVerificationError → 401 with detail."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(
                side_effect=JwtVerificationError("expired token")
            )
            mock_cls.return_value = mock_backend

            device_id = VALID_JWT_CLAIMS["device_id"]

            resp = client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=anything",
                headers={"Authorization": "Bearer expired.jwt.token"},
            )
            assert resp.status_code == 401
            detail = resp.json()["detail"]
            assert "JWT" in detail or "verification" in detail
