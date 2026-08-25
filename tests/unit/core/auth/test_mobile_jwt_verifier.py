"""Unit tests for MobileJwtVerifier (ADR-0262 / ADR-0264).

Tests cover:
1. Valid claims return MobileAuthContext with all fields
2. Invalid issuer raises
3. Invalid audience raises (string and list forms)
4. Missing/invalid device_id raises (not UUID v4 → fail)
5. Missing tenant_id raises
6. Missing jti raises
7. Empty token raises (via backend.decode error path)

Note: JWT encode/decode integration is tested separately in tests/unit/core/auth/.
These tests use a mocked backend to isolate MobileJwtVerifier logic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


def _make_mock_backend(claims: dict[str, Any] | Exception) -> Any:
    """Create a mock JwtBackend that returns given claims (or raises exception)."""
    backend = AsyncMock()
    if isinstance(claims, Exception):
        backend.decode = AsyncMock(side_effect=claims)
    else:
        backend.decode = AsyncMock(return_value=claims)
    return backend


def _make_verifier(backend: Any | None = None) -> Any:
    """Create MobileJwtVerifier with mock backend."""
    from src.backend.core.auth.mobile_jwt import MobileJwtVerifier

    if backend is None:
        # Valid baseline claims
        backend = _make_mock_backend(
            {
                "iss": "gd-mobile-test",
                "aud": "gd-mobile-api",
                "sub": "user_abc123",
                "device_id": "11111111-2222-4333-8444-555555555555",
                "tenant_id": "tenant_acme",
                "jti": "jti-test-001",
            }
        )
    return MobileJwtVerifier(
        backend=backend,
        issuer_whitelist=["gd-mobile-test", "gd-mobile-prod"],
        audience="gd-mobile-api",
    )


VALID_CLAIMS = {
    "iss": "gd-mobile-test",
    "aud": "gd-mobile-api",
    "sub": "user_abc123",
    "device_id": "11111111-2222-4333-8444-555555555555",
    "tenant_id": "tenant_acme",
    "jti": "jti-test-001",
}


pytestmark = pytest.mark.asyncio


async def test_valid_claims_returns_context() -> None:
    """Valid claims return MobileAuthContext with all fields."""
    verifier = _make_verifier()
    ctx = await verifier.verify("any.jwt.token")
    assert ctx.user_id == "user_abc123"
    assert ctx.device_id == "11111111-2222-4333-8444-555555555555"
    assert ctx.tenant_id == "tenant_acme"
    assert ctx.jti == "jti-test-001"


async def test_backend_decode_error_propagates() -> None:
    """JwtVerificationError from backend propagates to caller."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    backend = _make_mock_backend(JwtVerificationError("expired token"))
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="expired"):
        await verifier.verify("expired.jwt.token")


async def test_invalid_issuer_raises() -> None:
    """Token with iss not in whitelist raises JwtVerificationError."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {**VALID_CLAIMS, "iss": "evil-issuer"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="Invalid issuer"):
        await verifier.verify("any.jwt.token")


async def test_invalid_audience_string_raises() -> None:
    """Token with wrong aud (string form) raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {**VALID_CLAIMS, "aud": "wrong-audience"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="Invalid audience"):
        await verifier.verify("any.jwt.token")


async def test_invalid_audience_list_raises() -> None:
    """Token with aud list NOT containing expected raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {**VALID_CLAIMS, "aud": ["other-aud-1", "other-aud-2"]}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="Invalid audience"):
        await verifier.verify("any.jwt.token")


async def test_missing_device_id_raises() -> None:
    """Token without device_id claim raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {k: v for k, v in VALID_CLAIMS.items() if k != "device_id"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="Missing device_id"):
        await verifier.verify("any.jwt.token")


async def test_non_uuid_v4_device_id_raises() -> None:
    """Token with non-UUID device_id raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {**VALID_CLAIMS, "device_id": "not-a-uuid"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="Invalid device_id"):
        await verifier.verify("any.jwt.token")


async def test_uuid_v1_device_id_raises() -> None:
    """UUID v1 (not v4) fails mobile-specific validation."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    v1_uuid = "12345678-1234-1234-1234-123456789012"
    claims = {**VALID_CLAIMS, "device_id": v1_uuid}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="UUID v4"):
        await verifier.verify("any.jwt.token")


async def test_missing_tenant_id_raises() -> None:
    """Token without tenant_id claim raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {k: v for k, v in VALID_CLAIMS.items() if k != "tenant_id"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="tenant_id"):
        await verifier.verify("any.jwt.token")


async def test_empty_tenant_id_raises() -> None:
    """Token with empty tenant_id raises."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {**VALID_CLAIMS, "tenant_id": ""}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="tenant_id"):
        await verifier.verify("any.jwt.token")


async def test_missing_jti_raises() -> None:
    """Token without jti claim raises (needed for Phase 2 revocation)."""
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    claims = {k: v for k, v in VALID_CLAIMS.items() if k != "jti"}
    backend = _make_mock_backend(claims)
    verifier = _make_verifier(backend)
    with pytest.raises(JwtVerificationError, match="jti"):
        await verifier.verify("any.jwt.token")


async def test_verifier_requires_non_empty_issuer_whitelist() -> None:
    """Constructor rejects empty issuer_whitelist."""
    from src.backend.core.auth.mobile_jwt import MobileJwtVerifier

    backend = _make_mock_backend(VALID_CLAIMS)
    with pytest.raises(ValueError, match="issuer_whitelist"):
        MobileJwtVerifier(
            backend=backend,
            issuer_whitelist=[],
            audience="gd-mobile-api",
        )


async def test_verifier_requires_non_empty_audience() -> None:
    """Constructor rejects empty audience."""
    from src.backend.core.auth.mobile_jwt import MobileJwtVerifier

    backend = _make_mock_backend(VALID_CLAIMS)
    with pytest.raises(ValueError, match="audience"):
        MobileJwtVerifier(
            backend=backend,
            issuer_whitelist=["gd-mobile-test"],
            audience="",
        )


def test_context_dataclass_is_frozen() -> None:
    """MobileAuthContext is immutable (frozen dataclass)."""
    from src.backend.core.auth.mobile_jwt import MobileAuthContext

    ctx = MobileAuthContext(
        user_id="u1",
        device_id="11111111-2222-4333-8444-555555555555",
        tenant_id="t1",
        jti="j1",
    )
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError or similar
        ctx.user_id = "modified"  # type: ignore[misc]
