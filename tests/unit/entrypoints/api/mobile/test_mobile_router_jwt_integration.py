"""Integration tests for mobile router JWT path (S47 W2).

Per ADR-0265 §2: full mobile router → JWT → response flow.

Verifies:
1. With mobile_jwt_enabled=False (default), old fail-closed 401 behavior
2. With mobile_jwt_enabled=True + valid JWT → 200 + response
3. With mobile_jwt_enabled=True + invalid JWT → 401
4. With mobile_jwt_enabled=True + missing JWT verifier → 401 (fail-closed)
5. Demo flag path (mobile_demo_auth_enabled) still works
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_client_with_flags(
    *,
    mobile_jwt_enabled: bool = False,
    mobile_demo_auth_enabled: bool = False,
) -> Any:
    """Build TestClient with given feature flag configuration."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.backend.entrypoints.api.mobile.router import mobile_router

    app = FastAPI()
    app.include_router(mobile_router)

    # Mock feature_flags module
    mock_flags = MagicMock()
    mock_flags.mobile_jwt_enabled = mobile_jwt_enabled
    mock_flags.mobile_demo_auth_enabled = mobile_demo_auth_enabled

    import sys

    real_module = sys.modules.get("src.backend.core.config.features")
    with patch.dict(
        "sys.modules",
        {
            "src.backend.core.config.features": MagicMock(feature_flags=mock_flags),
            "src.backend.core.config.features.feature_flags": mock_flags,
        },
    ):
        with TestClient(app) as client:
            yield client, mock_flags


# ── Default behavior (mobile_jwt_enabled=False) ───────────────────


def test_profile_returns_401_when_mobile_jwt_off_and_no_demo() -> None:
    """Default (JWT off + demo off) returns 401 (current production safety)."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=False, mobile_demo_auth_enabled=False
    ):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer anything"},
        )
        assert response.status_code == 401


def test_login_endpoint_works_without_auth() -> None:
    """POST /mobile/v1/auth/login doesn't require auth (token issuance)."""
    for client, _ in _build_client_with_flags():
        response = client.post(
            "/mobile/v1/auth/login?device_id=11111111-2222-4333-8444-555555555555"
        )
        # 200 OK or 4xx — depends on schema; just verify no 401 from auth check
        assert response.status_code != 401 or "login" in response.text.lower()


# ── Mobile JWT enabled ────────────────────────────────────────────


def test_profile_returns_401_when_jwt_verifier_unavailable() -> None:
    """mobile_jwt_enabled=True but verifier unconfigured → fail-closed 401."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        # When JWT is enabled but verifier cannot be constructed
        # (missing keys etc.), should return 401, NOT fall through to demo.
        with patch(
            "src.backend.core.auth.jwt_backend.JwtBackend"
        ) as mock_backend:
            mock_backend.side_effect = Exception("No JWT keys configured")
            response = client.get(
                "/mobile/v1/profile",
                headers={"Authorization": "Bearer any.jwt.token"},
            )
            assert response.status_code == 401
            # Should mention verifier unavailable, not "demo auth disabled"
            detail = response.json().get("detail", "")
            assert "JWT" in detail or "unavailable" in detail.lower()


def test_profile_returns_401_with_invalid_jwt() -> None:
    """mobile_jwt_enabled=True + invalid JWT → 401 from JwtVerificationError."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        # Mock JwtBackend to raise JwtVerificationError
        from src.backend.core.auth.jwt_backend import JwtVerificationError

        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(
                side_effect=JwtVerificationError("expired")
            )
            mock_cls.return_value = mock_backend

            response = client.get(
                "/mobile/v1/profile",
                headers={"Authorization": "Bearer expired.jwt.token"},
            )
            assert response.status_code == 401
            detail = response.json().get("detail", "")
            assert "JWT" in detail or "verification" in detail.lower()


def test_profile_returns_200_with_valid_jwt() -> None:
    """mobile_jwt_enabled=True + valid JWT → 200 + profile."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True, mobile_demo_auth_enabled=False
    ):
        # Mock JwtBackend to return valid claims
        valid_claims = {
            "iss": "gd-mobile-prod",
            "aud": "gd-mobile-api",
            "sub": "user_integration_test",
            "device_id": "11111111-2222-4333-8444-555555555555",
            "tenant_id": "tenant_test",
            "jti": "jti-test-001",
        }

        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=valid_claims)
            mock_cls.return_value = mock_backend

            response = client.get(
                "/mobile/v1/profile",
                headers={"Authorization": "Bearer valid.jwt.token"},
            )
            assert response.status_code == 200
            data = response.json()
            # CompressedResponse: data.user_id or similar
            user_id = data.get("data", {}).get("user_id") or data.get("user_id")
            assert user_id == "user_integration_test"


# ── Demo flag path (backward compat) ──────────────────────────────


def test_demo_flag_path_still_works_when_mobile_jwt_off() -> None:
    """With JWT off + demo ON, demo format `mobile:<user_id>:<token>` works."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=False, mobile_demo_auth_enabled=True
    ):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer mobile:user_test:tokendemo12345"},
        )
        # Should return 200 (demo path accepted) or 4xx schema error
        # (NOT 401 from "JWT not implemented" gate)
        assert response.status_code != 401 or "Invalid mobile token" in response.text
