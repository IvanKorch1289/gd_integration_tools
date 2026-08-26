"""S62 W2 tests: edge cases for _verify_mobile_token (authorization header).

Edge cases that matter in production:
- Empty token after "Bearer " (trailing space only)
- "Bearer" without space (no token at all)
- Lowercase "bearer" (case sensitivity)
- Extra whitespace in token
- Demo auth disabled + demo format token → 401

Per S62 audit: real edge cases worth testing for auth path security.

Uses established ``for client, _ in _build_client_with_flags()`` pattern
from existing JWT integration tests to keep mock active during requests.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch


def _build_client_with_flags(
    *,
    mobile_demo_auth_enabled: bool = True,
    mobile_jwt_enabled: bool = False,
) -> Any:
    """Build TestClient with given feature flag configuration.

    Generator-style (yields once) so mock context is active during requests.
    Pattern from test_refresh_jwt_integration.py.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.backend.entrypoints.api.mobile.router import mobile_router

    app = FastAPI()
    app.include_router(mobile_router)

    flags_mock = MagicMock()
    flags_mock.mobile_jwt_enabled = mobile_jwt_enabled
    flags_mock.mobile_demo_auth_enabled = mobile_demo_auth_enabled

    with patch.dict(
        sys.modules,
        {
            "src.backend.core.config.features": MagicMock(feature_flags=flags_mock),
            "src.backend.core.config.features.feature_flags": flags_mock,
        },
    ):
        with TestClient(app) as client:
            yield client, flags_mock


# ── Edge case tests ──────────────────────────────────────────────────


def test_bearer_with_only_space_returns_401_invalid_format() -> None:
    """Authorization='Bearer ' (trailing space, empty token) → 401 invalid format."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=True):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer "},
        )
        assert response.status_code == 401
        # Token becomes empty after [7:] strips "Bearer " (7 chars)
        # Demo path: empty token doesn't start with "mobile:" → "Invalid mobile token format"
        detail = response.json()["detail"]
        assert "Invalid mobile token format" in detail or "Malformed" in detail


def test_bearer_without_space_returns_401_missing_header() -> None:
    """Authorization='Bearer' (no space, no token) → 401 missing header."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=True):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer"},
        )
        assert response.status_code == 401
        assert "Missing or invalid Authorization header" in response.json()["detail"]


def test_lowercase_bearer_returns_401_case_sensitive() -> None:
    """Authorization='bearer token' (lowercase) → 401 (case-sensitive check)."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=True):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "bearer mobile:user_test:tokendemo12345"},
        )
        # Strict case check: "bearer ..." doesn't start with "Bearer " (capital B + space)
        assert response.status_code == 401


def test_bearer_with_extra_whitespace_in_token() -> None:
    """Authorization='Bearer  mobile:user:token' (extra space) — token has leading space."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=True):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer  mobile:user_1:tokendemo12345"},
        )
        # After [7:] strips "Bearer " (7 chars including trailing space),
        # token becomes " mobile:user_1:tokendemo12345" (with leading space).
        # Doesn't start with "mobile:" → 401
        assert response.status_code == 401


def test_demo_disabled_blocks_demo_token_with_401() -> None:
    """demo_auth_enabled=False + demo format token → 401 (production safety)."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=False):
        device_id = "11111111-2222-4333-8444-555555555555"
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": f"Bearer mobile:user_{device_id[:8]}:tokendemo12345"},
        )
        assert response.status_code == 401
        assert "Mobile auth disabled" in response.json()["detail"]


def test_authorization_with_only_bearer_prefix_and_tab() -> None:
    """Authorization='Bearer\\ttoken' (tab not space) → 401 missing header."""
    for client, _ in _build_client_with_flags(mobile_demo_auth_enabled=True):
        response = client.get(
            "/mobile/v1/profile",
            headers={"Authorization": "Bearer\ttoken"},
        )
        # Strict check: "Bearer\t" doesn't start with "Bearer " (tab vs space)
        assert response.status_code == 401
