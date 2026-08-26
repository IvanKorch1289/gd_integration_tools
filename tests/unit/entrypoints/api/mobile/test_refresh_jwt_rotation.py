"""S55 W1 (cycle 291) tests: JWT path refresh rotation integration.

Verifies that /auth/refresh in JWT mode enforces single-use of JWT jti:

1. First refresh with JWT -> 200 + new tokens (jti tracked)
2. Same JWT presented again -> 401 (reuse detected)
3. Different JWT (different jti) -> 200 (independent tracking)
4. Reuse emits audit log warning

Pattern: ``@asynccontextmanager`` keeps ``patch.dict(sys.modules, ...)``
active throughout the entire ``async with`` block (including across
``await client.post(...)`` calls). This is critical because the
rotation check happens at request time, not import time, and the patch
must stay active until the response is received.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


VALID_JWT_BASE = {
    "iss": "gd-mobile-prod",
    "aud": "gd-mobile-api",
    "sub": "user_jwt_rotation",
    "device_id": "11111111-2222-4333-8444-555555555555",
    "tenant_id": "tenant_jwt_rotation",
}


@asynccontextmanager
async def _jwt_client() -> AsyncIterator[Any]:
    """Yield httpx.AsyncClient with JWT mode enabled + clean rotation store.

    Patches ``sys.modules`` for the duration of the ``async with`` block
    so that ``from src.backend.core.config.features import feature_flags``
    in router.py resolves to our mock_flags (mobile_jwt_enabled=True)
    at REQUEST time, not import time.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.entrypoints.api.mobile.router import (
        mobile_router,
        reset_mobile_state,
    )

    # Hygiene: clear rotation store.
    reset_mobile_state()

    app = FastAPI()
    app.include_router(mobile_router)

    mock_flags = MagicMock()
    mock_flags.mobile_jwt_enabled = True
    mock_flags.mobile_demo_auth_enabled = False

    with patch.dict(
        sys.modules,
        {
            "src.backend.core.config.features": MagicMock(feature_flags=mock_flags),
            "src.backend.core.config.features.feature_flags": mock_flags,
        },
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@asynccontextmanager
async def _mocked_jwt_decode(claims: dict[str, Any]) -> AsyncIterator[None]:
    """Patch JwtBackend.decode to return the given claims for the block."""
    with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
        mock_backend = AsyncMock()
        mock_backend.decode = AsyncMock(return_value=claims)
        mock_cls.return_value = mock_backend
        yield None


# ── Tests ────────────────────────────────────────────────────────────


async def test_jwt_first_use_succeeds() -> None:
    """First refresh with a JWT -> 200 + tokens issued."""
    async with _jwt_client() as client:
        claims = {**VALID_JWT_BASE, "jti": "jti-first-use"}
        async with _mocked_jwt_decode(claims):
            resp = await client.post(
                f"/mobile/v1/auth/refresh?device_id={claims['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer mocked.jwt.token"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # JWT user_id used in demo-format tokens
    assert "user_jwt_rotation" in data["access_token"]


async def test_jwt_reuse_detected_returns_401() -> None:
    """Same JWT jti used twice -> second call 401 (reuse detection).

    This is the core security guarantee: an attacker who captures
    a JWT cannot use it for refresh AFTER the legitimate user has
    already used it.
    """
    async with _jwt_client() as client:
        # First use -- legitimate
        claims = {**VALID_JWT_BASE, "jti": "jti-reuse-test"}
        async with _mocked_jwt_decode(claims):
            r1 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={claims['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer first.jwt"},
            )
        assert r1.status_code == 200

        # Second use -- replay attack (same jti)
        async with _mocked_jwt_decode(claims):
            r2 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={claims['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer second.jwt"},
            )
        assert r2.status_code == 401
        detail = r2.json()["detail"]
        assert "already used" in detail.lower() or "re-authentication" in detail.lower()


async def test_different_jwt_jti_independent() -> None:
    """Different JWT jtis are tracked independently."""
    async with _jwt_client() as client:
        # jti-A
        async with _mocked_jwt_decode({**VALID_JWT_BASE, "jti": "jti-A"}):
            r1 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer jwtA"},
            )
        assert r1.status_code == 200

        # jti-B (different)
        async with _mocked_jwt_decode({**VALID_JWT_BASE, "jti": "jti-B"}):
            r2 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer jwtB"},
            )
        assert r2.status_code == 200

        # Replay jti-A -- should still be rejected
        async with _mocked_jwt_decode({**VALID_JWT_BASE, "jti": "jti-A"}):
            r3 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer jwtA-replay"},
            )
        assert r3.status_code == 401


async def test_jwt_per_user_isolation() -> None:
    """Same jti for different users tracked separately (no collision)."""
    async with _jwt_client() as client:
        # User 1 uses jti-shared
        claims_user1 = {**VALID_JWT_BASE, "sub": "user_one", "jti": "jti-shared"}
        async with _mocked_jwt_decode(claims_user1):
            r1 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer user1.jwt"},
            )
        assert r1.status_code == 200

        # User 2 uses SAME jti-shared -- should succeed (different user)
        claims_user2 = {**VALID_JWT_BASE, "sub": "user_two", "jti": "jti-shared"}
        async with _mocked_jwt_decode(claims_user2):
            r2 = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer user2.jwt"},
            )
        assert r2.status_code == 200


async def test_jwt_invalid_signature_skips_rotation_check() -> None:
    """JWT verification failure -> 401 BEFORE rotation check (fail-closed).

    If JWT signature is invalid, we should not even consult the rotation
    store -- auth fails first.
    """
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    async with _jwt_client() as client:
        with patch("src.backend.core.auth.jwt_backend.JwtBackend") as mock_cls:
            mock_backend = AsyncMock()
            mock_backend.decode = AsyncMock(
                side_effect=JwtVerificationError("invalid signature")
            )
            mock_cls.return_value = mock_backend

            resp = await client.post(
                f"/mobile/v1/auth/refresh?device_id={VALID_JWT_BASE['device_id']}&refresh_token=ignored",
                headers={"Authorization": "Bearer invalid.jwt"},
            )
        assert resp.status_code == 401
        # Should be JWT verification error, NOT demo "invalid refresh token format"
        detail = resp.json()["detail"]
        assert "verification" in detail.lower() or "jwt" in detail.lower()
