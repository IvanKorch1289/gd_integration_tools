"""S57 W2 tests: verify audit log format matches OWASP evidence document.

The OWASP_V35_MOBILE_AUTH_EVIDENCE.md document claims specific log message
formats for refresh reuse detection events. These tests verify the actual
log output matches the documented format — critical for compliance retention
and ops alerting.

Tests verify:
- Demo path reuse: "mobile refresh reuse detected (family revoked)" with
  structured fields (user, device, jti, tokens_invalidated)
- JWT path reuse: "JWT refresh reuse detected (family revoked)" with
  same structured fields
- Successful refresh: "mobile refresh via JWT: user=X jti=Y"
- Reuse count >= 1 when family revoked
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


VALID_JWT_BASE = {
    "iss": "gd-mobile-prod",
    "aud": "gd-mobile-api",
    "sub": "user_jwt_audit_test",
    "device_id": "11111111-2222-4333-8444-555555555557",
    "tenant_id": "tenant_jwt_audit_test",
}


@asynccontextmanager
async def _jwt_client_with_log_capture(
    caplog: pytest.LogCaptureFixture,
) -> AsyncIterator[Any]:
    """Build jwt client with log capture."""
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


# ── Demo path audit log format ────────────────────────────────────────


async def test_demo_reuse_audit_log_format(caplog: pytest.LogCaptureFixture) -> None:
    """Demo path reuse detected → log message matches documented format.

    Format (per OWASP evidence doc):
    'mobile refresh reuse detected (family revoked): user=X device=Y
     jti=Z tokens_invalidated=N'
    """
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
    with caplog.at_level(logging.WARNING, logger="src.backend.entrypoints.api.mobile.router"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            device_id = "11111111-2222-4333-8444-555555555558"

            # Login → track refresh token
            login_resp = await client.post(
                f"/mobile/v1/auth/login?device_id={device_id}"
            )
            assert login_resp.status_code == 200
            refresh_token = login_resp.json()["refresh_token"]

            # Refresh (rotate)
            await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
            )

            # Reuse original (triggers reuse detection + family revoke)
            await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token={refresh_token}"
            )

    # Verify warning log was emitted with documented format
    log_text = caplog.text
    assert "mobile refresh reuse detected (family revoked)" in log_text, (
        f"Expected documented format, got: {log_text}"
    )
    assert "user=" in log_text, f"Missing user= field: {log_text}"
    assert "device=" in log_text, f"Missing device= field: {log_text}"
    assert "jti=" in log_text, f"Missing jti= field: {log_text}"
    assert "tokens_invalidated=" in log_text, (
        f"Missing tokens_invalidated= field: {log_text}"
    )


# ── JWT path audit log format ─────────────────────────────────────────


async def test_jwt_reuse_audit_log_format(caplog: pytest.LogCaptureFixture) -> None:
    """JWT path reuse detected → log message matches documented format.

    Format (per OWASP evidence doc):
    'JWT refresh reuse detected (family revoked): user=X device=Y
     jti=Z tokens_invalidated=N'
    """
    async with _jwt_client_with_log_capture(caplog) as client:
        device_id = VALID_JWT_BASE["device_id"]

        # First use — legitimate
        claims = {**VALID_JWT_BASE, "jti": "jti-audit-test"}
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=claims)
            mock_cls.return_value = mock_backend

            r1 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=ignored",
                headers={"Authorization": "Bearer first.jwt"},
            )
            assert r1.status_code == 200

        # Reuse — triggers family revocation
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(return_value=claims)
            mock_cls.return_value = mock_backend

            r2 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=ignored",
                headers={"Authorization": "Bearer replay.jwt"},
            )
            assert r2.status_code == 401

    # Verify log format
    log_text = caplog.text
    assert "JWT refresh reuse detected (family revoked)" in log_text, (
        f"Expected documented format, got: {log_text}"
    )
    assert "tokens_invalidated=" in log_text
    # jti is truncated to 8 chars (per refresh_token_store.py format)
    assert "jti=jti-audi" in log_text  # truncated


async def test_jwt_successful_refresh_log_format(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful JWT refresh → INFO log with user_id and jti."""
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

    device_id = VALID_JWT_BASE["device_id"]
    claims = {**VALID_JWT_BASE, "jti": "jti-success-test"}

    with caplog.at_level(logging.INFO, logger="src.backend.entrypoints.api.mobile.router"):
        with patch.dict(
            __import__("sys").modules,
            {
                "src.backend.core.config.features": MagicMock(feature_flags=mock_flags),
                "src.backend.core.config.features.feature_flags": mock_flags,
            },
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
                    mock_backend = AsyncMock()
                    mock_backend.decode = AsyncMock(return_value=claims)
                    mock_cls.return_value = mock_backend

                    resp = await client.post(
                        f"/mobile/v1/auth/refresh?device_id={device_id}&refresh_token=ignored",
                        headers={"Authorization": "Bearer valid.jwt"},
                    )
                    assert resp.status_code == 200

    log_text = caplog.text
    assert "mobile refresh via JWT" in log_text, f"Got: {log_text}"
    assert "user_id=user_jwt_audit_test" in log_text
    assert "jti=jti-succ" in log_text  # truncated


# ── Audit log count for ops alerting ──────────────────────────────────


async def test_revoke_family_returns_count_for_audit() -> None:
    """revoke_family returns count of invalidated tokens (for audit logging).

    Ops alerting on this count > N indicates attack attempts.
    """
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()

    # Issue 5 tokens for same (user, device)
    for jti in ["jti-1", "jti-2", "jti-3", "jti-4", "jti-5"]:
        await store.issue("user1", "device1", jti, ttl_seconds=3600)

    # Revoke family
    removed = await store.revoke_family("user1", "device1")
    assert removed == 5  # all 5 tokens invalidated


async def test_audit_count_zero_when_family_empty() -> None:
    """revoke_family on empty family returns 0 (no audit noise)."""
    from src.backend.entrypoints.api.mobile.refresh_token_store import (
        InMemoryRefreshTokenStore,
    )

    store = InMemoryRefreshTokenStore()
    removed = await store.revoke_family("never-issued-user", "never-issued-device")
    assert removed == 0
